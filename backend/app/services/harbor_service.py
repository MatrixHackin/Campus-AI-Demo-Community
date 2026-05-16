from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import Settings

logger = logging.getLogger(__name__)


class HarborService:
    """Harbor 只读镜像仓库服务。

    第一版只读查询工作台需要的镜像项目：
    - “我的镜像”：当前登录用户邮箱对应的私有项目
    - “公有镜像”：HARBOR_PUBLIC_PROJECT 指定的项目
    - 不自动创建 Harbor 用户
    - 不自动创建 Harbor 项目
    - 不开放删除镜像/项目
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.harbor_url
            and self.settings.harbor_admin_username
            and self.settings.harbor_admin_password
        )

    @property
    def registry(self) -> str:
        return self.settings.harbor_registry.rstrip('/')

    def user_project_name(self, email: str) -> str:
        safe_email = email.strip().lower().replace('@', '-at-').replace('.', '-dot-')
        return f'{safe_email}{self.settings.harbor_user_project_suffix}'

    def get_user_projects(self, email: str | None, include_tags: bool = False) -> dict:
        base_response = {
            'configured': self.configured,
            'registry': self.registry,
            'public_project': self.settings.harbor_public_project or None,
            'private_project_name': None,
            'private_project': None,
            'public_project_info': None,
            'message': None,
            'private_message': None,
            'public_message': None,
        }

        if not self.configured:
            base_response['message'] = 'Harbor 未配置'
            return base_response

        public_project_name = self.settings.harbor_public_project.strip()
        if public_project_name:
            public_project = self._get_project(public_project_name, include_tags=include_tags, include_quota=False)
            base_response['public_project_info'] = public_project
            if public_project.get('error'):
                base_response['public_message'] = public_project['error']
            elif not public_project['exists']:
                base_response['public_message'] = f'未找到 Harbor 公有项目：{public_project_name}'
        else:
            base_response['public_message'] = '未配置 Harbor 公有项目'

        if not email:
            base_response['private_message'] = '当前登录用户缺少邮箱，无法匹配 Harbor 私有项目'
            return base_response

        project_name = self.user_project_name(email)
        base_response['private_project_name'] = project_name
        project = self._get_project(project_name, include_tags=include_tags, include_quota=False)
        base_response['private_project'] = project
        if project.get('error'):
            base_response['private_message'] = project['error']
        elif not project['exists']:
            base_response['private_message'] = '未找到当前邮箱对应的 Harbor 私有项目'
        return base_response

    def get_user_private_project(self, email: str | None, include_tags: bool = False) -> dict:
        return self.get_user_projects(email=email, include_tags=include_tags)

    def _harbor_url(self) -> str:
        return self.settings.harbor_url.rstrip('/') + '/'

    def _admin_auth(self) -> HTTPBasicAuth:
        return HTTPBasicAuth(self.settings.harbor_admin_username, self.settings.harbor_admin_password)

    def _timeout(self) -> int:
        return self.settings.harbor_request_timeout_seconds

    def _get_project_id(self, project_name: str) -> int | None:
        response = requests.get(
            f'{self._harbor_url()}projects',
            params={'name': project_name},
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        response.raise_for_status()
        projects = response.json()
        if not projects:
            return None
        return int(projects[0]['project_id'])

    def _get_project(self, project_name: str, include_tags: bool = False, include_quota: bool = True) -> dict:
        result = {
            'project_name': project_name,
            'exists': False,
            'quota': {'used': {}, 'limit': {}},
            'repos': [],
            'error': None,
        }

        try:
            if include_quota:
                project_id = self._get_project_id(project_name)
                if project_id is None:
                    return result
                result['exists'] = True
                result['quota'] = self._get_project_quota(project_id)

            repos, repo_project_exists, repo_error = self._get_project_repos(project_name, include_tags=include_tags)
            result['repos'] = repos
            result['exists'] = result['exists'] or repo_project_exists
            result['error'] = repo_error
        except requests.RequestException as exc:
            logger.warning('Harbor project query failed for %s: %s', project_name, exc)
            result['quota'] = {'used': {}, 'limit': {}}
            result['error'] = f'Harbor 查询失败：{exc}'
        except Exception as exc:
            logger.warning('Unexpected Harbor project query failure for %s: %s', project_name, exc)
            result['error'] = f'Harbor 查询异常：{exc}'

        return result

    def _get_project_quota(self, project_id: int) -> dict:
        response = requests.get(
            f'{self._harbor_url()}projects/{project_id}/summary',
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        if response.status_code != 200:
            logger.warning('Harbor project summary query failed: HTTP %s', response.status_code)
            return {'used': {}, 'limit': {}}

        quota = response.json().get('quota') or {}
        return {
            'used': quota.get('used') or {},
            'limit': quota.get('hard') or {},
        }

    def _get_project_repos(self, project_name: str, include_tags: bool = False) -> tuple[list[dict], bool, str | None]:
        try:
            encoded_project_name = quote(project_name, safe='')
            response = requests.get(
                f'{self._harbor_url()}projects/{encoded_project_name}/repositories',
                params={'page_size': 100},
                auth=self._admin_auth(),
                timeout=self._timeout(),
            )
        except requests.RequestException as exc:
            logger.warning('Harbor repository query failed for %s: %s', project_name, exc)
            return [], False, f'Harbor 仓库查询失败：{exc}'

        if response.status_code == 404:
            return [], False, None

        if response.status_code in {401, 403}:
            logger.warning('Harbor repository auth failed for %s: HTTP %s', project_name, response.status_code)
            return [], False, f'Harbor 认证或权限不足：HTTP {response.status_code}'

        if response.status_code != 200:
            logger.warning(
                'Harbor repository query failed for %s: HTTP %s %s',
                project_name,
                response.status_code,
                response.text,
            )
            return [], False, f'Harbor 仓库查询失败：HTTP {response.status_code}'

        repos = []
        for repo in response.json():
            repo_name = repo['name'].split('/')[-1]
            repo_info = {
                'name': repo_name,
                'full_name': repo['name'],
                'image': f'{self.registry}/{repo["name"]}:latest',
                'artifact_count': repo.get('artifact_count', 0),
                'pull_count': repo.get('pull_count', 0),
                'update_time': repo.get('update_time'),
                'tags': self._get_repo_tags(project_name, repo_name) if include_tags else [],
            }
            repos.append(repo_info)
        return repos, True, None

    def _get_repo_tags(self, project_name: str, repo_name: str) -> list[str]:
        try:
            encoded_repo_name = quote(repo_name, safe='')
            response = requests.get(
                f'{self._harbor_url()}projects/{project_name}/repositories/{encoded_repo_name}/artifacts',
                params={'page_size': 100, 'with_tag': 'true'},
                auth=self._admin_auth(),
                timeout=self._timeout(),
            )
            if response.status_code != 200:
                return []

            tags: list[str] = []
            seen: set[str] = set()
            for artifact in response.json():
                for tag in artifact.get('tags') or []:
                    tag_name = tag.get('name')
                    if tag_name and tag_name not in seen:
                        seen.add(tag_name)
                        tags.append(tag_name)
            return tags
        except Exception as exc:
            logger.warning('Harbor tag query failed for %s/%s: %s', project_name, repo_name, exc)
            return []
