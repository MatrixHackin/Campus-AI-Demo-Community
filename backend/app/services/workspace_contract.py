from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class WorkspaceContract:
    """开发沙盒里应用代码、数据和运行镜像的固定路径。"""

    app_name: str
    mount_path: str
    path_prefix: str
    listen_port: int = 3000

    @classmethod
    def from_settings(cls, settings: Settings, app_name: str) -> WorkspaceContract:
        mount = (settings.k3s_user_workspace_mount_path or '/mydata').strip() or '/mydata'
        prefix = (settings.k3s_apps_path_prefix or '/apps').strip() or '/apps'
        return cls(app_name=app_name, mount_path=mount, path_prefix=prefix)

    @property
    def source_dir(self) -> str:
        return f'{self.mount_path.rstrip("/")}/apps/{self.app_name}'

    @property
    def data_dir(self) -> str:
        return f'{self.mount_path.rstrip("/")}/data/{self.app_name}'

    @property
    def dockerfile_path(self) -> str:
        return f'{self.source_dir}/Dockerfile'

    @property
    def base_path(self) -> str:
        prefix = '/' + self.path_prefix.strip('/')
        return f'{prefix}/{self.app_name}/'

    def as_dict(self) -> dict:
        return {
            'app_name': self.app_name,
            'listen_host': '0.0.0.0',
            'listen_port': self.listen_port,
            'base_path': self.base_path,
            'source_dir': self.source_dir,
            'dockerfile': self.dockerfile_path,
            'data_dir': self.data_dir,
        }

    def contract_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)

    def guide_text(self) -> str:
        return (
            f'应用名：{self.app_name}\n'
            f'请把代码和 Dockerfile 放在 {self.source_dir}\n'
            f'进程监听 0.0.0.0:{self.listen_port}，页面 base path 为 {self.base_path}\n'
            f'需要长期保存的数据放在 {self.data_dir}，不要打进运行镜像。\n'
            '发布时平台只根据该目录的 Dockerfile 构建运行镜像，并在集群里单独启动。\n'
            '开发沙盒本身不会被提交成应用镜像。\n'
        )

    def agent_system_prompt(self) -> str:
        return (
            f'你是 Campus AI 的开发 Agent，正在用户的开发沙盒里开发应用「{self.app_name}」。\n'
            '你只能通过工具读写这个开发沙盒。用中文说明你做了什么。\n'
            '下面这些路径决定页面资源能否加载，以及发布后的运行镜像能否启动。不要把代码写到别的目录：\n'
            f'- 应用代码目录：{self.source_dir}\n'
            f'- Dockerfile：{self.dockerfile_path}\n'
            f'- 持久数据目录：{self.data_dir}。这里的数据不要复制进镜像。\n'
            f'- 开发预览进程监听 0.0.0.0:{self.listen_port}\n'
            f'- Web 的 base path 必须是 {self.base_path}。静态资源、路由和接口前缀都要带上它，不能只写根路径。\n'
            '发布时平台不会把整个开发沙盒打成镜像，只会按 Dockerfile 构建运行镜像，再在集群里单独启动。\n'
            '因此 Dockerfile 必须能独立启动服务。规则如下：\n'
            '- 只使用 FROM、WORKDIR、COPY、ENV、EXPOSE、RUN、CMD、ENTRYPOINT\n'
            '- 基础镜像必须包含 /bin/sh\n'
            '- 用 COPY . /app 这种相对应用目录的复制，不要复制数据目录\n'
            f'- 设置 ENV BASE_PATH={self.base_path}\n'
            f'- 必须写出 CMD 或 ENTRYPOINT，最终进程监听 0.0.0.0:{self.listen_port}\n'
            '- 不要使用多阶段构建、ARG 和通配符\n'
            '工具参数 path 相对应用代码目录。写完代码和 Dockerfile 后，在应用目录里做一次启动前检查。\n'
            '不要把模型密钥写进代码、Dockerfile 或镜像。'
        )

    def web_agent_prompt(self, message: str, history: list[dict] | None) -> str:
        """给 web-agent-runtime 的单次 prompt。它只接收这一段文字和 workspace。"""
        lines = [
            self.agent_system_prompt(),
            '可用工具只有 read_file、save_file、list_file、run。路径使用相对应用代码目录的路径。',
            'Git 提交由运行时完成，不要自己 commit 或 push。',
        ]
        prior = []
        for item in (history or [])[-8:]:
            role = item.get('role')
            content = item.get('content')
            if role not in {'user', 'assistant'} or not isinstance(content, str) or not content.strip():
                continue
            speaker = '用户' if role == 'user' else '开发环境'
            prior.append(f'{speaker}：{content.strip()[:2000]}')
        if prior:
            lines.append('最近对话：\n' + '\n'.join(prior))
        lines.append(f'这一轮要完成：\n{message.strip()}')
        return '\n\n'.join(lines)
