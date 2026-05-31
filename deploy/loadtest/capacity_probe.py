from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import quantiles
from typing import Iterable

import asyncssh

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / 'backend'
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.deps import k3s_service, settings  # noqa: E402


@dataclass(slots=True)
class Stats:
    name: str
    ok: int = 0
    failed: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, ok: bool, latency_ms: float | None = None) -> None:
        if ok:
            self.ok += 1
        else:
            self.failed += 1
        if latency_ms is not None:
            self.latencies_ms.append(latency_ms)

    @property
    def total(self) -> int:
        return self.ok + self.failed

    @property
    def failure_rate(self) -> float:
        return self.failed / self.total if self.total else 0.0

    def p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        if len(self.latencies_ms) < 20:
            return max(self.latencies_ms)
        return quantiles(self.latencies_ms, n=20)[18]

    def summary(self) -> str:
        return (
            f'{self.name}: total={self.total} ok={self.ok} failed={self.failed} '
            f'failure_rate={self.failure_rate:.2%} p95_ms={self.p95():.1f}'
        )


@dataclass(frozen=True, slots=True)
class SSHTarget:
    app_name: str
    login_name: str
    password: str


async def run_ssh_worker(
    worker_id: int,
    target: SSHTarget,
    *,
    host: str,
    port: int,
    command_interval: float,
    stop_event: asyncio.Event,
    stats: Stats,
) -> None:
    conn: asyncssh.SSHClientConnection | None = None
    try:
        started = time.perf_counter()
        conn = await asyncssh.connect(
            host,
            port=port,
            username=target.login_name,
            password=target.password,
            known_hosts=None,
            login_timeout=20,
        )
        stats.record(True, (time.perf_counter() - started) * 1000)
        while not stop_event.is_set():
            command_started = time.perf_counter()
            try:
                result = await conn.run('printf ok', check=True, timeout=15)
                stats.record(result.stdout == 'ok', (time.perf_counter() - command_started) * 1000)
            except Exception:
                stats.record(False, (time.perf_counter() - command_started) * 1000)
                break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=command_interval)
            except TimeoutError:
                continue
    except Exception as exc:
        logging.warning('ssh worker failed worker=%s app=%s error=%s', worker_id, target.app_name, exc)
        stats.record(False)
    finally:
        if conn:
            conn.close()
            await conn.wait_closed()


async def run_http_worker(
    worker_id: int,
    *,
    host: str,
    port: int,
    request_host: str,
    paths: list[str],
    cookie: str | None,
    think_seconds: float,
    stop_event: asyncio.Event,
    stats: Stats,
) -> None:
    index = worker_id % len(paths)
    while not stop_event.is_set():
        path = paths[index % len(paths)]
        index += 1
        started = time.perf_counter()
        try:
            reader, writer = await asyncio.open_connection(host, port)
            headers = [
                f'GET {path} HTTP/1.1',
                f'Host: {request_host}',
                'User-Agent: campus-ai-capacity-probe/1.0',
                'Connection: close',
            ]
            if cookie:
                headers.append(f'Cookie: {cookie}')
            request = '\r\n'.join(headers) + '\r\n\r\n'
            writer.write(request.encode('utf-8'))
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=10)
            status = status_line.decode('iso-8859-1', errors='replace').split(' ', 2)
            ok = len(status) >= 2 and status[1].isdigit() and int(status[1]) < 500
            await reader.read()
            writer.close()
            await writer.wait_closed()
            stats.record(ok, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            logging.warning('http worker failed worker=%s path=%s error=%s', worker_id, path, exc)
            stats.record(False, (time.perf_counter() - started) * 1000)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=think_seconds)
        except TimeoutError:
            continue


def parse_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(',') if item.strip()]


def parse_csv_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(',') if item.strip()]


def load_ssh_targets(app_names: Iterable[str]) -> list[SSHTarget]:
    targets: list[SSHTarget] = []
    for app_name in app_names:
        record = k3s_service.container_repository.get_container_record_by_app_name(app_name=app_name)
        if not record:
            raise RuntimeError(f'missing container record for app: {app_name}')
        ssh_username = record.get('ssh_username') or record.get('username')
        password = record.get('password')
        if not ssh_username or not password:
            raise RuntimeError(f'missing ssh credentials for app: {app_name}')
        targets.append(
            SSHTarget(
                app_name=app_name,
                login_name=f'{ssh_username}+{record["app_name"]}',
                password=password,
            )
        )
    return targets


def login_cookie() -> str | None:
    conn = http.client.HTTPConnection('127.0.0.1', 8001, timeout=10)
    payload = json.dumps({'username': settings.demo_username, 'password': settings.demo_password})
    try:
        conn.request('POST', '/api/v1/auth/login', body=payload, headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        body = response.read()
        if response.status >= 400:
            logging.warning('control-plane login failed status=%s body=%s', response.status, body[:120])
            return None
        token = json.loads(body.decode('utf-8'))['access_token']
        return f'{settings.session_cookie_name}={token}'
    finally:
        conn.close()


async def run_stage(
    *,
    name: str,
    seconds: int,
    ssh_concurrency: int,
    http_concurrency: int,
    control_concurrency: int,
    ssh_targets: list[SSHTarget],
    app_paths: list[str],
    control_paths: list[str],
    args: argparse.Namespace,
    global_stop: asyncio.Event,
    cookie: str | None,
) -> bool:
    logging.info(
        'stage start name=%s seconds=%s ssh=%s apps_http=%s control_http=%s',
        name,
        seconds,
        ssh_concurrency,
        http_concurrency,
        control_concurrency,
    )
    stage_stop = asyncio.Event()
    stats = [
        Stats('ssh'),
        Stats('apps_http'),
        Stats('control_http'),
    ]

    tasks: list[asyncio.Task] = []
    for worker_id in range(ssh_concurrency):
        target = ssh_targets[worker_id % len(ssh_targets)]
        tasks.append(
            asyncio.create_task(
                run_ssh_worker(
                    worker_id,
                    target,
                    host=args.ssh_host,
                    port=args.ssh_port,
                    command_interval=args.ssh_command_interval,
                    stop_event=stage_stop,
                    stats=stats[0],
                )
            )
        )
        await asyncio.sleep(args.ssh_ramp_delay)

    for worker_id in range(http_concurrency):
        tasks.append(
            asyncio.create_task(
                run_http_worker(
                    worker_id,
                    host=args.http_host,
                    port=args.http_port,
                    request_host=args.request_host,
                    paths=app_paths,
                    cookie=None,
                    think_seconds=args.http_think_seconds,
                    stop_event=stage_stop,
                    stats=stats[1],
                )
            )
        )

    for worker_id in range(control_concurrency):
        tasks.append(
            asyncio.create_task(
                run_http_worker(
                    worker_id,
                    host=args.http_host,
                    port=args.http_port,
                    request_host=args.request_host,
                    paths=control_paths,
                    cookie=cookie,
                    think_seconds=args.control_think_seconds,
                    stop_event=stage_stop,
                    stats=stats[2],
                )
            )
        )

    try:
        await asyncio.wait_for(global_stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
    finally:
        stage_stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    for item in stats:
        logging.info('stage summary name=%s %s', name, item.summary())

    failed = False
    for item in stats:
        if item.total and item.failure_rate > args.max_failure_rate:
            logging.warning(
                'stage stop threshold exceeded name=%s metric=%s failure_rate=%.2f%% threshold=%.2f%%',
                name,
                item.name,
                item.failure_rate * 100,
                args.max_failure_rate * 100,
            )
            failed = True
        if item.name == 'ssh' and item.p95() > args.max_ssh_p95_ms:
            logging.warning(
                'stage stop threshold exceeded name=%s metric=ssh_p95 p95_ms=%.1f threshold_ms=%.1f',
                name,
                item.p95(),
                args.max_ssh_p95_ms,
            )
            failed = True
        if item.name.endswith('http') and item.p95() > args.max_http_p95_ms:
            logging.warning(
                'stage stop threshold exceeded name=%s metric=%s_p95 p95_ms=%.1f threshold_ms=%.1f',
                name,
                item.name,
                item.p95(),
                args.max_http_p95_ms,
            )
            failed = True
    return not failed and not global_stop.is_set()


async def main() -> None:
    parser = argparse.ArgumentParser(description='Low-disruption capacity probe for Campus AI.')
    parser.add_argument('--ssh-host', default='10.120.17.138')
    parser.add_argument('--ssh-port', type=int, default=2222)
    parser.add_argument('--http-host', default='10.120.17.138')
    parser.add_argument('--http-port', type=int, default=8080)
    parser.add_argument('--request-host', default='gpunion.hkust-gz.edu.cn')
    parser.add_argument('--ssh-apps', default='test,my-app')
    parser.add_argument('--app-paths', default='/apps/colorpicker,/apps/time-converter')
    parser.add_argument('--control-paths', default='/api/health,/api/v1/community/apps')
    parser.add_argument('--ssh-stages', default='50,100,200')
    parser.add_argument('--http-stages', default='25,50,100')
    parser.add_argument('--stage-seconds', type=int, default=300)
    parser.add_argument('--combo-seconds', type=int, default=300)
    parser.add_argument('--combo-ssh', type=int, default=200)
    parser.add_argument('--combo-http', type=int, default=50)
    parser.add_argument('--combo-control', type=int, default=20)
    parser.add_argument('--ssh-ramp-delay', type=float, default=0.05)
    parser.add_argument('--ssh-command-interval', type=float, default=5.0)
    parser.add_argument('--http-think-seconds', type=float, default=1.0)
    parser.add_argument('--control-think-seconds', type=float, default=2.0)
    parser.add_argument('--max-failure-rate', type=float, default=0.02)
    parser.add_argument('--max-ssh-p95-ms', type=float, default=5000.0)
    parser.add_argument('--max-http-p95-ms', type=float, default=2000.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('asyncssh').setLevel(logging.WARNING)
    global_stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(getattr(signal, signame), global_stop.set)

    ssh_targets = load_ssh_targets(parse_csv_strings(args.ssh_apps))
    app_paths = parse_csv_strings(args.app_paths)
    control_paths = parse_csv_strings(args.control_paths)
    cookie = login_cookie()
    logging.info(
        'capacity probe started ssh_apps=%s app_paths=%s control_cookie=%s',
        [target.app_name for target in ssh_targets],
        app_paths,
        'yes' if cookie else 'no',
    )

    for concurrency in parse_csv_ints(args.ssh_stages):
        should_continue = await run_stage(
            name=f'ssh-{concurrency}',
            seconds=args.stage_seconds,
            ssh_concurrency=concurrency,
            http_concurrency=0,
            control_concurrency=0,
            ssh_targets=ssh_targets,
            app_paths=app_paths,
            control_paths=control_paths,
            args=args,
            global_stop=global_stop,
            cookie=cookie,
        )
        if not should_continue:
            logging.warning('capacity probe stopped after stage ssh-%s', concurrency)
            return

    for concurrency in parse_csv_ints(args.http_stages):
        should_continue = await run_stage(
            name=f'apps-http-{concurrency}',
            seconds=args.stage_seconds,
            ssh_concurrency=0,
            http_concurrency=concurrency,
            control_concurrency=max(1, min(concurrency // 5, 20)),
            ssh_targets=ssh_targets,
            app_paths=app_paths,
            control_paths=control_paths,
            args=args,
            global_stop=global_stop,
            cookie=cookie,
        )
        if not should_continue:
            logging.warning('capacity probe stopped after stage apps-http-%s', concurrency)
            return

    await run_stage(
        name='combo',
        seconds=args.combo_seconds,
        ssh_concurrency=args.combo_ssh,
        http_concurrency=args.combo_http,
        control_concurrency=args.combo_control,
        ssh_targets=ssh_targets,
        app_paths=app_paths,
        control_paths=control_paths,
        args=args,
        global_stop=global_stop,
        cookie=cookie,
    )
    logging.info('capacity probe finished')


if __name__ == '__main__':
    asyncio.run(main())
