from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import select
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from app.core.config import Settings
from app.services.k3s_service import K3SService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SSHTarget:
    app_name: str
    namespace: str
    pod_name: str | None
    ssh_username: str
    password: str
    service_name: str
    host: str
    port: int = 22


class _PortForwardTCPBridge:
    """把 Kubernetes port-forward socket 转成 uvloop/AsyncSSH 兼容的本地 TCP 端口。"""

    def __init__(self, port_forward, remote_port: int) -> None:
        self._port_forward = port_forward
        self._remote_port = remote_port
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(('127.0.0.1', 0))
        self._listener.listen(1)
        self.host, self.port = self._listener.getsockname()
        self._client_sock = None
        self._remote_sock = None
        self._thread = threading.Thread(
            target=self._run,
            name=f'campus-ai-k8s-portforward-{remote_port}',
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self._listener.settimeout(30)
            client_sock, _ = self._listener.accept()
            self._client_sock = client_sock
            self._remote_sock = self._port_forward.socket(self._remote_port)
            client_sock.setblocking(False)
            self._remote_sock.setblocking(False)

            sockets = [client_sock, self._remote_sock]
            while not self._stop.is_set():
                readable, _, _ = select.select(sockets, [], [], 0.5)
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    target_sock = self._remote_sock if sock is client_sock else client_sock
                    target_sock.sendall(data)
        except OSError:
            return
        except Exception as exc:
            logger.warning('Kubernetes SSH port-forward TCP bridge 异常：%s', exc)
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        for sock in (self._client_sock, self._remote_sock, self._listener):
            if sock is not None:
                with contextlib.suppress(Exception):
                    sock.close()
        with contextlib.suppress(Exception):
            self._port_forward.close()


class _TargetSSHConnection:
    def __init__(self, ssh_conn, bridge: _PortForwardTCPBridge | None = None) -> None:
        self._ssh_conn = ssh_conn
        self._bridge = bridge

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ssh_conn, name)

    def close(self) -> None:
        self._ssh_conn.close()
        if self._bridge is not None:
            with contextlib.suppress(Exception):
                self._bridge.close()

    async def wait_closed(self) -> None:
        try:
            await self._ssh_conn.wait_closed()
        finally:
            if self._bridge is not None:
                with contextlib.suppress(Exception):
                    self._bridge.close()


class SSHGatewayService:
    """WebSSH 与原生 SSH 网关。

    - WebSSH：FastAPI WebSocket -> AsyncSSH client -> Pod SSH Service
    - 原生 SSH：AsyncSSH server :2222 -> AsyncSSH client -> Pod SSH Service
    """

    def __init__(self, settings: Settings, k3s_service: K3SService) -> None:
        self.settings = settings
        self.k3s_service = k3s_service
        self._server = None

    async def start(self) -> None:
        if not self.settings.ssh_gateway_enabled:
            return

        try:
            import asyncssh

            server_host_key = self._load_or_create_server_host_key()
            for attempt in range(1, 11):
                try:
                    self._server = await asyncssh.create_server(
                        lambda: _NativeSSHServer(self),
                        self.settings.ssh_gateway_host,
                        self.settings.ssh_gateway_port,
                        server_host_keys=[server_host_key],
                        reuse_address=True,
                    )
                    break
                except OSError as exc:
                    if exc.errno != errno.EADDRINUSE or attempt >= 10:
                        raise
                    logger.warning(
                        'SSH Gateway 端口 %s 暂时被占用，等待后重试（%s/10）',
                        self.settings.ssh_gateway_port,
                        attempt,
                    )
                    await asyncio.sleep(1)
            logger.info(
                'SSH Gateway started on %s:%s',
                self.settings.ssh_gateway_host,
                self.settings.ssh_gateway_port,
            )
        except OSError as exc:
            logger.error('SSH Gateway 启动失败：%s', exc)
            raise

    def _load_or_create_server_host_key(self):
        """读取固定 HostKey；未配置时生成临时 HostKey。"""
        import asyncssh

        host_key_path = self.settings.ssh_gateway_host_key_path
        if not host_key_path:
            return asyncssh.generate_private_key('ssh-ed25519')

        path = Path(host_key_path).expanduser()
        if path.exists():
            return asyncssh.read_private_key(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        key = asyncssh.generate_private_key('ssh-ed25519')
        key.write_private_key(path)
        path.chmod(0o600)
        return key

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    def resolve_target(
        self,
        *,
        app_name: str,
        ssh_username: str,
        owner_username: str | None = None,
        password: str | None = None,
    ) -> SSHTarget:
        target = self.k3s_service.get_ssh_target(
            app_name=app_name,
            ssh_username=ssh_username,
            owner_username=owner_username,
            password=password,
        )
        return SSHTarget(
            app_name=target['app_name'],
            namespace=target['namespace'],
            pod_name=target.get('pod_name'),
            ssh_username=target['ssh_username'],
            password=target['password'],
            service_name=target['service_name'],
            host=target['host'],
            port=target['port'],
        )

    async def connect_target(self, target: SSHTarget):
        import asyncssh

        if target.pod_name:
            bridge = await asyncio.to_thread(self._open_pod_tcp_bridge, target)
            try:
                ssh_conn = await asyncssh.connect(
                    bridge.host,
                    port=bridge.port,
                    username=target.ssh_username,
                    password=target.password,
                    known_hosts=None,
                    login_timeout=15,
                )
                return _TargetSSHConnection(ssh_conn, bridge)
            except Exception:
                bridge.close()
                raise

        ssh_conn = await asyncssh.connect(
            target.host,
            port=target.port,
            username=target.ssh_username,
            password=target.password,
            known_hosts=None,
            login_timeout=15,
        )
        return _TargetSSHConnection(ssh_conn)

    def _open_pod_tcp_bridge(self, target: SSHTarget) -> _PortForwardTCPBridge:
        from kubernetes import client
        from kubernetes.stream import portforward

        # 先调用一次确保 kubeconfig/in-cluster config 已加载；随后使用新的 CoreV1Api
        # 实例，避免 kubernetes.stream.portforward 临时 monkeypatch 共享 ApiClient，
        # 干扰并发的普通 Kubernetes API 请求。
        self.k3s_service._core()
        core_v1 = client.CoreV1Api()
        port_forward = portforward(
            core_v1.connect_get_namespaced_pod_portforward,
            target.pod_name,
            target.namespace,
            ports=str(target.port),
        )
        error = port_forward.error(target.port)
        if error:
            port_forward.close()
            raise RuntimeError(f'Pod SSH port-forward 失败：{error}')
        if not port_forward.connected:
            port_forward.close()
            raise RuntimeError('Pod SSH port-forward 未连接')
        return _PortForwardTCPBridge(port_forward, target.port)

    async def bridge_websocket(self, websocket: WebSocket, target: SSHTarget) -> None:
        """把 WebSocket 输入输出桥接到目标容器 SSH shell。"""
        ssh_conn = None
        process = None
        try:
            ssh_conn = await self.connect_target(target)
            process = await ssh_conn.create_process(term_type='xterm-256color', term_size=(100, 32))

            async def websocket_to_ssh() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get('type') == 'websocket.disconnect':
                        break
                    data = message.get('text')
                    if data is None and message.get('bytes') is not None:
                        data = message['bytes'].decode('utf-8', errors='ignore')
                    if data:
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            process.stdin.write(data)
                            continue

                        if not isinstance(payload, dict):
                            continue
                        if payload.get('type') == 'resize':
                            cols = int(payload.get('cols') or 100)
                            rows = int(payload.get('rows') or 32)
                            process.change_terminal_size(cols, rows)
                        elif payload.get('type') == 'data':
                            process.stdin.write(payload.get('data') or '')

            async def ssh_stream_to_websocket(reader) -> None:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    await websocket.send_text(data)

            input_task = asyncio.create_task(websocket_to_ssh())
            stdout_task = asyncio.create_task(ssh_stream_to_websocket(process.stdout))
            stderr_task = asyncio.create_task(ssh_stream_to_websocket(process.stderr))
            process_task = asyncio.create_task(process.wait())
            tasks = {input_task, stdout_task, stderr_task, process_task}
            output_tasks = {stdout_task, stderr_task}

            while tasks:
                done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    tasks.discard(task)
                    output_tasks.discard(task)
                    task.result()

                if input_task in done or process_task in done or not output_tasks:
                    break

            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if process is not None:
                with contextlib.suppress(Exception):
                    process.close()
            if ssh_conn is not None:
                ssh_conn.close()
                await ssh_conn.wait_closed()


class _NativeSSHServer:
    def __init__(self, gateway: SSHGatewayService) -> None:
        import asyncssh

        class Server(asyncssh.SSHServer):
            def __init__(self) -> None:
                self.target: SSHTarget | None = None

            def begin_auth(self, username: str) -> bool:
                return True

            def password_auth_supported(self) -> bool:
                return True

            def validate_password(self, username: str, password: str) -> bool:
                if '+' not in username:
                    return False
                ssh_username, app_name = username.rsplit('+', 1)
                if not ssh_username or not app_name:
                    return False
                try:
                    self.target = gateway.resolve_target(
                        app_name=app_name,
                        ssh_username=ssh_username,
                        password=password,
                    )
                    return True
                except Exception as exc:
                    logger.warning('原生 SSH 登录校验失败：%s', exc)
                    return False

            def session_requested(self):
                if self.target is None:
                    return False
                return _NativeSSHSession(gateway, self.target)

        self._server = Server()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._server, name)


class _NativeSSHSession:
    def __init__(self, gateway: SSHGatewayService, target: SSHTarget) -> None:
        self.gateway = gateway
        self.target = target
        self.channel = None
        self.ssh_conn = None
        self.process = None
        self.term_type = 'xterm-256color'
        self.term_size = (100, 32)
        self.command: str | None = None
        self._pending_input: list[Any] = []
        self._pending_eof = False

    def connection_made(self, channel) -> None:
        self.channel = channel

    def pty_requested(self, term_type, term_size, term_modes) -> bool:
        self.term_type = term_type or self.term_type
        self.term_size = term_size or self.term_size
        return True

    def shell_requested(self) -> bool:
        return True

    def exec_requested(self, command: str) -> bool:
        self.command = command
        return True

    def session_started(self) -> None:
        asyncio.create_task(self._start())

    def data_received(self, data, datatype) -> None:
        if self.process is not None:
            self.process.stdin.write(data)
        else:
            self._pending_input.append(data)

    def eof_received(self) -> bool:
        if self.process is not None:
            self.process.stdin.write_eof()
        else:
            self._pending_eof = True
        return False

    def terminal_size_changed(self, width, height, pixwidth, pixheight) -> None:
        if self.process is not None:
            self.process.change_terminal_size(width, height, pixwidth, pixheight)

    def connection_lost(self, exc) -> None:
        if self.process is not None:
            with contextlib.suppress(Exception):
                self.process.close()
        if self.ssh_conn is not None:
            with contextlib.suppress(Exception):
                self.ssh_conn.close()

    async def _start(self) -> None:
        try:
            self.ssh_conn = await self.gateway.connect_target(self.target)
            if self.command is not None:
                result = await self.ssh_conn.run(self.command, check=False)
                if self.channel is not None:
                    if result.stdout:
                        self.channel.write(result.stdout)
                    if result.stderr:
                        self.channel.write(result.stderr)
                    self.channel.exit(result.exit_status or 0)
                return

            self.process = await self.ssh_conn.create_process(
                term_type=self.term_type,
                term_size=self.term_size,
            )
            for data in self._pending_input:
                self.process.stdin.write(data)
            self._pending_input.clear()
            if self._pending_eof:
                self.process.stdin.write_eof()

            async def forward_stream(reader) -> None:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    if self.channel is not None:
                        self.channel.write(data)

            stdout_task = asyncio.create_task(forward_stream(self.process.stdout))
            stderr_task = asyncio.create_task(forward_stream(self.process.stderr))
            await self.process.wait()
            try:
                await asyncio.wait_for(
                    asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
                    timeout=2,
                )
            except TimeoutError:
                for task in (stdout_task, stderr_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            if self.channel is not None:
                self.channel.exit(self.process.exit_status or 0)
        except Exception as exc:
            logger.warning('原生 SSH 代理会话失败：%s', exc)
            if self.channel is not None:
                with contextlib.suppress(Exception):
                    self.channel.write(f'\r\nSSH gateway error: {exc}\r\n')
                with contextlib.suppress(Exception):
                    self.channel.exit(1)
        finally:
            if self.ssh_conn is not None:
                self.ssh_conn.close()
                await self.ssh_conn.wait_closed()
