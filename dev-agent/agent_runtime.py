"""Campus AI 开发 Agent runtime。

模型密钥由调用方按请求传入，不写进镜像，也不保存在这个进程里。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'list_dir',
            'description': '列出应用代码目录中的文件',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': '相对应用代码目录的路径，空字符串表示目录本身'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': '读取应用代码目录中的文件',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': '相对应用代码目录的路径'},
                },
                'required': ['path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_file',
            'description': '把文件写到应用代码目录。需要目录时会自动创建。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': '相对应用代码目录的路径'},
                    'content': {'type': 'string', 'description': '完整文件内容'},
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'run_command',
            'description': '在应用代码目录中执行 shell 命令，用于安装依赖和检查能否启动',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string', 'description': '要执行的 shell 命令'},
                },
                'required': ['command'],
            },
        },
    },
]


class AgentModelError(RuntimeError):
    pass


def run_turn(
    *,
    api_base: str,
    api_key: str,
    model: str,
    system_prompt: str,
    history: list[dict] | None,
    message: str,
    tool_handler,
    max_rounds: int = 6,
    timeout: int = 90,
    on_step=None,
) -> dict:
    messages: list[dict] = [{'role': 'system', 'content': system_prompt}]
    for item in (history or [])[-12:]:
        role = item.get('role')
        content = item.get('content')
        if role in {'user', 'assistant'} and isinstance(content, str) and content.strip():
            messages.append({'role': role, 'content': content[:8000]})
    messages.append({'role': 'user', 'content': message})

    steps: list[dict] = []
    for _ in range(max_rounds):
        choice = _chat(api_base, api_key, model, messages, timeout)
        tool_calls = choice.get('tool_calls') or []
        if not tool_calls:
            return {
                'reply': choice.get('content') or '已完成。',
                'steps': steps,
            }
        messages.append({
            'role': 'assistant',
            'content': choice.get('content') or '',
            'tool_calls': tool_calls,
        })
        for call in tool_calls:
            function = call.get('function') or {}
            name = function.get('name') or ''
            raw_args = function.get('arguments') or '{}'
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            try:
                output = tool_handler(name, args)
                ok = True
            except Exception as exc:
                output = str(exc)
                ok = False
            step = {
                'tool': name,
                'ok': ok,
                'summary': _summarize(name, args),
            }
            steps.append(step)
            if on_step:
                on_step(step)
            messages.append({
                'role': 'tool',
                'tool_call_id': call.get('id') or name,
                'content': str(output)[:8000],
            })
    return {
        'reply': '这一轮工具调用已达上限。可以再发一条消息，让我继续改代码或检查启动命令。',
        'steps': steps,
    }


def _chat(api_base: str, api_key: str, model: str, messages: list[dict], timeout: int) -> dict:
    url = api_base.rstrip('/') + '/chat/completions'
    payload = {
        'model': model,
        'messages': messages,
        'tools': TOOLS,
        'temperature': 0.2,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:300]
        if exc.code == 400 and 'tool' in detail.lower():
            raise AgentModelError('当前模型接口不支持工具调用，请换成兼容 OpenAI tools 的模型') from exc
        raise AgentModelError(f'模型接口返回 HTTP {exc.code}') from exc
    except urllib.error.URLError as exc:
        raise AgentModelError(f'无法连接模型接口：{exc.reason}') from exc
    choices = data.get('choices') or []
    if not choices or not isinstance(choices[0], dict):
        raise AgentModelError('模型接口没有返回有效内容')
    message = choices[0].get('message')
    if not isinstance(message, dict):
        raise AgentModelError('模型接口没有返回有效内容')
    return message


def _summarize(name: str, args: dict) -> str:
    if name == 'write_file':
        return f'写入 {args.get("path") or "文件"}'
    if name == 'read_file':
        return f'读取 {args.get("path") or "文件"}'
    if name == 'list_dir':
        return f'查看 {args.get("path") or "应用目录"}'
    if name == 'run_command':
        command = str(args.get('command') or '').strip().replace('\n', ' ')
        return f'执行 {command[:80]}' if command else '执行命令'
    return name or '工具调用'
