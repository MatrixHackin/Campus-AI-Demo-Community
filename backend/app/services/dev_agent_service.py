from __future__ import annotations

import importlib.util
import json
import logging
import secrets
import shlex
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import Settings
from app.services.agent_settings_repository import AgentSettingsRepository
from app.services.k3s_service import K3SService
from app.services.workspace_contract import WorkspaceContract

logger = logging.getLogger(__name__)

_RUNTIME = None
_MAX_FILE_BYTES = 256 * 1024
_MAX_OUTPUT_CHARS = 8000


def _runtime():
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    path = Path(__file__).resolve().parents[3] / 'dev-agent' / 'agent_runtime.py'
    spec = importlib.util.spec_from_file_location('campus_ai_agent_runtime', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('开发 Agent runtime 不存在')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _RUNTIME = module
    return module


class DevAgentService:
    def __init__(self, settings: Settings, k3s_service: K3SService) -> None:
        self.settings = settings
        self.k3s_service = k3s_service
        self.repository = AgentSettingsRepository(settings)
        self._runs: dict[str, dict] = {}
        self._chat_runs: dict[str, dict] = {}
        self._chat_lock = threading.Lock()

    def list_settings(self, username: str) -> list[dict]:
        return [self._public_config(row) for row in self.repository.list(username)]

    def create_settings(
        self,
        *,
        username: str,
        api_base: str,
        model_name: str,
        api_key: str | None,
    ) -> dict:
        if self.repository.count(username) >= 20:
            raise ValueError('最多保存 20 组模型配置')
        normalized_base, normalized_model, next_key = self._normalize_config(
            api_base,
            model_name,
            api_key,
            require_key=True,
        )
        saved = self.repository.create(
            username=username,
            api_base=normalized_base,
            model_name=normalized_model,
            api_key=next_key or '',
        )
        return self._public_config(saved)

    def update_settings(
        self,
        *,
        username: str,
        config_id: int,
        api_base: str,
        model_name: str,
        api_key: str | None,
    ) -> dict:
        existing = self.repository.get_owned(username, config_id)
        if not existing:
            raise ValueError('这组模型配置不存在')
        normalized_base, normalized_model, next_key = self._normalize_config(
            api_base,
            model_name,
            api_key,
            require_key=False,
        )
        saved = self.repository.update(
            username=username,
            config_id=config_id,
            api_base=normalized_base,
            model_name=normalized_model,
            api_key=next_key,
        )
        if not saved:
            raise ValueError('这组模型配置不存在')
        return self._public_config(saved)

    def delete_settings(self, *, username: str, config_id: int) -> None:
        if not self.repository.delete(username, config_id):
            raise ValueError('这组模型配置不存在')

    def start_chat(
        self,
        *,
        emp_id: str | None,
        username: str,
        pod_name: str,
        message: str,
        history: list[dict] | None,
        config_id: int,
    ) -> str:
        run_id = secrets.token_urlsafe(18)
        record = {
            'username': username,
            'status': 'running',
            'steps': [],
            'reply': '',
            'error': '',
            'updated_at': time.time(),
        }
        self._chat_runs[run_id] = record
        history_copy = [dict(item) for item in (history or [])]

        def on_step(step: dict) -> None:
            with self._chat_lock:
                record['steps'].append(dict(step))
                record['updated_at'] = time.time()

        def worker() -> None:
            try:
                result = self.chat(
                    emp_id=emp_id,
                    username=username,
                    pod_name=pod_name,
                    message=message,
                    history=history_copy,
                    config_id=config_id,
                    on_step=on_step,
                )
                with self._chat_lock:
                    record['reply'] = result.get('reply') or ''
                    record['steps'] = list(result.get('steps') or record['steps'])
                    record['status'] = 'done'
                    record['updated_at'] = time.time()
            except Exception as exc:
                logger.exception('开发 Agent 本轮失败')
                message_text = str(exc) if isinstance(exc, (ValueError, FileNotFoundError, PermissionError, RuntimeError)) else '开发 Agent 调用失败'
                with self._chat_lock:
                    record['error'] = message_text
                    record['status'] = 'error'
                    record['updated_at'] = time.time()

        threading.Thread(target=worker, name=f'agent-chat-{run_id[:6]}', daemon=True).start()
        return run_id

    def get_chat_run(self, *, username: str, run_id: str) -> dict:
        self._expire_chat_runs()
        with self._chat_lock:
            record = self._chat_runs.get(run_id)
            if not record or record.get('username') != username:
                raise FileNotFoundError('这一轮已经结束或不存在')
            return {
                'status': record['status'],
                'steps': list(record['steps']),
                'reply': record.get('reply') or '',
                'error': record.get('error') or '',
            }

    def _expire_chat_runs(self) -> None:
        now = time.time()
        with self._chat_lock:
            for run_id, record in list(self._chat_runs.items()):
                idle = now - float(record.get('updated_at') or now)
                if record.get('status') == 'running' and idle > 900:
                    record['status'] = 'error'
                    record['error'] = '这一轮超时了。已经写入的文件还在，可以再发一条消息继续。'
                    record['updated_at'] = now
                elif record.get('status') != 'running' and idle > 1800:
                    self._chat_runs.pop(run_id, None)

    def chat(
        self,
        *,
        emp_id: str | None,
        username: str,
        pod_name: str,
        message: str,
        history: list[dict] | None,
        config_id: int,
        on_step=None,
    ) -> dict:
        text = message.strip()
        if not text:
            raise ValueError('请输入开发需求')
        if len(text) > 8000:
            raise ValueError('单条消息最多 8000 个字符')
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法使用开发 Agent')

        settings_row = self.repository.get_owned(username, config_id)
        if not settings_row or not settings_row.get('api_key'):
            raise ValueError('请选择已保存的模型配置')

        namespace = self.k3s_service.namespace_for_emp_id(emp_id)
        record = self.k3s_service.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            raise FileNotFoundError('未找到开发沙盒')
        if record.get('username') and record['username'] != username:
            raise PermissionError('无权使用该开发沙盒')
        app_name = record.get('app_name')
        if not app_name:
            raise ValueError('开发沙盒缺少应用名称')

        contract = WorkspaceContract.from_settings(self.settings, app_name)
        self._ensure_contract_files(namespace, pod_name, contract)
        backend = (self.settings.dev_agent_backend or 'auto').strip().lower()
        agent_base = self.k3s_service.dev_agent_base_url(namespace, pod_name)
        if backend == 'web-agent' and not agent_base:
            raise RuntimeError('这个开发沙盒还没有 web-agent-runtime。新建沙盒后会带上它。')
        if agent_base and backend in {'auto', 'web-agent'}:
            return self._chat_web_agent(
                settings_row,
                contract,
                text,
                history or [],
                agent_base,
                on_step=on_step,
            )
        token = secrets.token_urlsafe(32)
        self._runs[token] = {
            'namespace': namespace,
            'pod_name': pod_name,
            'source_dir': contract.source_dir,
            'expires_at': time.time() + self.settings.dev_agent_timeout_seconds + 30,
        }
        try:
            if self.settings.dev_agent_url.strip():
                return self._chat_remote(settings_row, contract, text, history or [], token)
            runtime = _runtime()
            return runtime.run_turn(
                api_base=settings_row['api_base'],
                api_key=settings_row['api_key'],
                model=settings_row['model_name'],
                system_prompt=contract.agent_system_prompt(),
                history=history or [],
                message=text,
                tool_handler=lambda name, args: self.execute_tool(token, name, args),
                timeout=min(90, self.settings.dev_agent_timeout_seconds),
                on_step=on_step,
            )
        except runtime_error_type() as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            self._runs.pop(token, None)

    def _chat_web_agent(
        self,
        settings_row: dict,
        contract: WorkspaceContract,
        message: str,
        history: list[dict],
        agent_base: str,
        on_step=None,
    ) -> dict:
        if on_step:
            on_step({
                'tool': 'run',
                'ok': True,
                'summary': '已交给沙盒中的 web-agent-runtime',
            })
        payload = {
            'prompt': contract.web_agent_prompt(message, history),
            'workspace': contract.source_dir,
            'provider': {
                'base_url': settings_row['api_base'],
                'model': settings_row['model_name'],
                'api_key': settings_row['api_key'],
            },
        }
        request = urllib.request.Request(
            agent_base.rstrip('/') + '/v1/turns',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.dev_agent_timeout_seconds) as response:
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')
            message_text = 'web-agent-runtime 调用失败'
            try:
                parsed = json.loads(detail)
                error = parsed.get('error') or {}
                message_text = error.get('message') or parsed.get('detail') or message_text
            except json.JSONDecodeError:
                pass
            raise RuntimeError(message_text) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'无法连接沙盒中的 web-agent-runtime：{exc.reason}') from exc
        if not isinstance(body, dict):
            raise RuntimeError('web-agent-runtime 没有返回结果')
        error = body.get('error') or {}
        if body.get('status') != 'completed':
            raise RuntimeError(error.get('message') or 'web-agent-runtime 没有完成这一轮')
        count = int(body.get('steps') or 0)
        steps = []
        if count:
            steps.append({
                'tool': 'run',
                'ok': True,
                'summary': f'web-agent-runtime 完成 {count} 次工具调用',
            })
        if on_step:
            for step in steps:
                on_step(step)
        return {'reply': body.get('text') or '', 'steps': steps}

    def execute_tool(self, token: str, name: str, arguments: dict | None) -> str:
        run = self._runs.get(token)
        if not run or run['expires_at'] < time.time():
            raise PermissionError('开发会话已结束')
        args = arguments or {}
        source_dir = run['source_dir']
        if name == 'list_dir':
            path = self._safe_path(source_dir, str(args.get('path') or '.'))
            return self._exec(run, f'ls -la {shlex.quote(path)}', as_user=False)
        if name == 'read_file':
            path = self._safe_path(source_dir, str(args.get('path') or ''))
            output = self._exec(
                run,
                f'if [ ! -f {shlex.quote(path)} ]; then echo 文件不存在; exit 0; fi; cat {shlex.quote(path)}',
                as_user=False,
            )
            if len(output) > _MAX_OUTPUT_CHARS:
                return output[:_MAX_OUTPUT_CHARS] + '\n...文件过长，已截断'
            return output
        if name == 'write_file':
            path = self._safe_path(source_dir, str(args.get('path') or ''))
            content = args.get('content')
            if not isinstance(content, str):
                raise ValueError('文件内容必须是文本')
            if len(content.encode()) > _MAX_FILE_BYTES:
                raise ValueError('单个文件不能超过 256KB')
            parent = path.rsplit('/', 1)[0] or source_dir
            encoded = _b64(content)
            script = (
                f'mkdir -p {shlex.quote(parent)} && '
                f'printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}'
            )
            self._exec(run, script, as_user=True)
            return f'已写入 {path}'
        if name == 'run_command':
            command = args.get('command')
            if not isinstance(command, str) or not command.strip():
                raise ValueError('缺少命令')
            if len(command) > 4000:
                raise ValueError('命令过长')
            return self._exec(run, f'cd {shlex.quote(source_dir)} && {command}', as_user=True, timeout=60)
        raise ValueError('不支持的工具')

    def _chat_remote(self, settings_row: dict, contract: WorkspaceContract, message: str, history: list[dict], token: str) -> dict:
        tool_base = self.settings.dev_agent_tool_base_url.rstrip('/')
        payload = {
            'api_base': settings_row['api_base'],
            'api_key': settings_row['api_key'],
            'model': settings_row['model_name'],
            'system_prompt': contract.agent_system_prompt(),
            'history': history,
            'message': message,
            'tool_url': f'{tool_base}/internal/agent/tool',
            'tool_token': token,
            'timeout': min(90, self.settings.dev_agent_timeout_seconds),
        }
        request = urllib.request.Request(
            self.settings.dev_agent_url.rstrip('/') + '/v1/run',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.dev_agent_timeout_seconds) as response:
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')
            try:
                parsed = json.loads(detail)
                message_text = parsed.get('detail') or '开发 Agent 调用失败'
            except json.JSONDecodeError:
                message_text = '开发 Agent 调用失败'
            raise RuntimeError(message_text) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'无法连接开发 Agent：{exc.reason}') from exc
        if not isinstance(body, dict) or 'reply' not in body:
            raise RuntimeError('开发 Agent 没有返回结果')
        return body

    def _ensure_contract_files(self, namespace: str, pod_name: str, contract: WorkspaceContract) -> None:
        parent = contract.source_dir.rsplit('/', 1)[0]
        contract_path = f'{contract.source_dir}/.campus-ai/contract.json'
        guide_path = f'{contract.source_dir}/CAMPUS_AI.md'
        script = (
            f'mkdir -p {shlex.quote(contract.source_dir)}/.campus-ai {shlex.quote(contract.data_dir)} {shlex.quote(parent)} && '
            f'printf %s {shlex.quote(_b64(contract.contract_json()))} | base64 -d > {shlex.quote(contract_path)} && '
            f'if [ ! -f {shlex.quote(guide_path)} ]; then '
            f'printf %s {shlex.quote(_b64(contract.guide_text()))} | base64 -d > {shlex.quote(guide_path)}; fi; '
            f'chown -R "$USERNAME:$USERNAME" {shlex.quote(contract.source_dir)} {shlex.quote(contract.data_dir)} '
            '2>/dev/null || true'
        )
        try:
            self.k3s_service.exec_shell(namespace, pod_name, script, timeout=20)
        except Exception as exc:
            logger.warning('写入开发路径约定失败，继续对话：%s', exc)

    def _exec(self, run: dict, script: str, *, as_user: bool, timeout: int = 30) -> str:
        command = script
        if as_user:
            command = (
                'if id "$USERNAME" >/dev/null 2>&1; then '
                f'su -s /bin/sh "$USERNAME" -c {shlex.quote(script)}; '
                f'else {script}; fi'
            )
        stdout, stderr, code = self.k3s_service.exec_shell(
            run['namespace'],
            run['pod_name'],
            command,
            timeout=timeout,
        )
        output = stdout
        if stderr.strip():
            output = f'{output}\n{stderr}'.strip()
        output = output.strip() or '完成'
        if code not in (0, None):
            output = f'退出码 {code}\n{output}'
        if len(output) > _MAX_OUTPUT_CHARS:
            return output[:_MAX_OUTPUT_CHARS] + '\n...输出过长，已截断'
        return output

    @staticmethod
    def _safe_path(source_dir: str, raw: str) -> str:
        if not raw or raw == '.':
            return source_dir
        candidate = raw if raw.startswith('/') else f'{source_dir.rstrip("/")}/{raw}'
        parts: list[str] = []
        for part in candidate.split('/'):
            if part in {'', '.'}:
                continue
            if part == '..':
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        normalized = '/' + '/'.join(parts)
        root = source_dir.rstrip('/')
        if normalized != root and not normalized.startswith(root + '/'):
            raise ValueError('只能访问当前应用的代码目录')
        return normalized

    @staticmethod
    def _normalize_api_base(api_base: str) -> str:
        value = api_base.strip().rstrip('/')
        if not value.startswith(('http://', 'https://')) or any(char.isspace() for char in value):
            raise ValueError('模型接口地址需要以 http:// 或 https:// 开头')
        if len(value) > 512:
            raise ValueError('模型接口地址过长')
        return value

    def _normalize_config(
        self,
        api_base: str,
        model_name: str,
        api_key: str | None,
        *,
        require_key: bool,
    ) -> tuple[str, str, str | None]:
        normalized_base = self._normalize_api_base(api_base)
        normalized_model = (model_name or '').strip()
        if not normalized_model or len(normalized_model) > 128:
            raise ValueError('请填写模型名称')
        next_key = (api_key or '').strip()
        if not next_key:
            if require_key:
                raise ValueError('请填写模型 API Key')
            return normalized_base, normalized_model, None
        if len(next_key) > 1024:
            raise ValueError('模型 API Key 过长')
        return normalized_base, normalized_model, next_key

    @staticmethod
    def _public_config(row: dict) -> dict:
        api_key = row.get('api_key') or ''
        hint = ''
        if api_key:
            hint = f'已保存（尾号 {api_key[-4:]}）' if len(api_key) >= 4 else '已保存'
        return {
            'id': int(row['id']),
            'api_base': row.get('api_base') or 'https://api.deepseek.com/v1',
            'model_name': row.get('model_name') or 'deepseek-chat',
            'has_api_key': bool(api_key),
            'api_key_hint': hint,
        }


def runtime_error_type():
    return _runtime().AgentModelError


def _b64(content: str) -> str:
    import base64
    return base64.b64encode(content.encode()).decode()
