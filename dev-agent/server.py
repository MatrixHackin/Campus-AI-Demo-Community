#!/usr/bin/env python3
"""开发 Agent runtime 的 HTTP 入口。

部署在 k3s Pod 中。模型密钥只出现在单次请求里。
工具调用回传到 Campus AI 后端，由后端进入用户的开发沙盒。
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

from agent_runtime import AgentModelError, run_turn


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] == '/health':
            self._send(200, {'status': 'ok'})
            return
        self._send(404, {'detail': 'not found'})

    def do_POST(self):
        if self.path.split('?', 1)[0] != '/v1/run':
            self._send(404, {'detail': 'not found'})
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > 2_000_000:
            self._send(400, {'detail': '请求体不合法'})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode())
            result = run_turn(
                api_base=payload['api_base'],
                api_key=payload['api_key'],
                model=payload['model'],
                system_prompt=payload['system_prompt'],
                history=payload.get('history') or [],
                message=payload['message'],
                tool_handler=lambda name, args: _remote_tool(
                    payload['tool_url'],
                    payload['tool_token'],
                    name,
                    args,
                ),
                timeout=int(payload.get('timeout') or 90),
            )
        except KeyError as exc:
            self._send(400, {'detail': f'缺少字段 {exc.args[0]}'})
            return
        except AgentModelError as exc:
            self._send(502, {'detail': str(exc)})
            return
        except Exception as exc:
            self._send(500, {'detail': str(exc)})
            return
        self._send(200, result)

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        return


def _remote_tool(url: str, token: str, name: str, arguments: dict) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps({'token': token, 'name': name, 'arguments': arguments}).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode())
    if not body.get('ok'):
        raise RuntimeError(body.get('error') or '工具执行失败')
    return str(body.get('output') or '')


def main() -> None:
    port = int(os.environ.get('PORT', '8080'))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
