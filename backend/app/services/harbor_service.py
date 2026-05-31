from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import Settings

logger = logging.getLogger(__name__)


class HarborService:
    """Harbor 镜像仓库服务。

    查询工作台需要的镜像项目：
    - “我的镜像”：当前登录用户邮箱对应的私有项目
    - “公有镜像”：HARBOR_PUBLIC_PROJECT 指定的项目
    同时在用户点击“保存容器”前，按邮箱确保 Harbor 用户和私有项目存在。
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

    def ensure_user_private_project(self, email: str) -> dict:
        """确保 Harbor 用户和私有项目存在。

        与 GPUnion2-server 保持一致：用户名使用邮箱，项目名使用邮箱转义后加 -repo，
        项目设为 private，并把用户加入项目 developer 角色。
        """
        if not self.configured:
            raise RuntimeError('镜像仓库暂不可用')
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError('缺少用户邮箱，无法准备个人镜像仓库')

        user_id = self._ensure_user(normalized_email)
        project_name = self.user_project_name(normalized_email)
        project_id = self._ensure_project(project_name)
        self._ensure_project_member(project_id, user_id)
        return {
            'user_id': user_id,
            'project_id': project_id,
            'project_name': project_name,
            'username': normalized_email,
        }

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
            base_response['message'] = '镜像仓库暂不可用'
            return base_response

        public_project_name = self.settings.harbor_public_project.strip()
        if public_project_name:
            public_project = self._get_project(public_project_name, include_tags=include_tags, include_quota=False)
            base_response['public_project_info'] = public_project
            if public_project.get('error'):
                base_response['public_message'] = public_project['error']
            elif not public_project['exists']:
                base_response['public_message'] = '暂无可用公有镜像'
        else:
            base_response['public_message'] = '暂无可用公有镜像'

        if not email:
            base_response['private_message'] = '当前账号缺少邮箱，无法加载个人镜像'
            return base_response

        project_name = self.user_project_name(email)
        base_response['private_project_name'] = project_name
        project = self._get_project(project_name, include_tags=include_tags, include_quota=False)
        base_response['private_project'] = project
        if project.get('error'):
            base_response['private_message'] = project['error']
        elif not project['exists']:
            base_response['private_message'] = '暂无个人镜像'
        return base_response

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

    def _get_user_id(self, username: str) -> int | None:
        response = requests.get(
            f'{self._harbor_url()}users',
            params={'username': username},
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        response.raise_for_status()
        users = response.json()
        if not users:
            return None
        return int(users[0]['user_id'])

    def _ensure_user(self, email: str) -> int:
        user_id = self._get_user_id(email)
        if user_id is not None:
            return user_id

        response = requests.post(
            f'{self._harbor_url()}users',
            json={
                'username': email,
                'password': self.settings.harbor_user_default_password,
                'email': email,
                'realname': email,
                'comment': 'auto-created by Campus AI',
            },
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        if response.status_code not in {201, 409}:
            raise RuntimeError(f'准备镜像仓库账号失败：HTTP {response.status_code}')

        user_id = self._get_user_id(email)
        if user_id is None:
            raise RuntimeError('准备镜像仓库账号失败')
        return user_id

    def _ensure_project(self, project_name: str) -> int:
        project_id = self._get_project_id(project_name)
        if project_id is not None:
            return project_id

        response = requests.post(
            f'{self._harbor_url()}projects',
            json={
                'project_name': project_name,
                'metadata': {'public': 'false'},
                'storage_limit': self.settings.harbor_user_default_storage_quota,
            },
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        if response.status_code not in {201, 409}:
            raise RuntimeError(f'准备个人镜像仓库失败：HTTP {response.status_code}')

        project_id = self._get_project_id(project_name)
        if project_id is None:
            raise RuntimeError('准备个人镜像仓库失败')
        return project_id

    def _ensure_project_member(self, project_id: int, user_id: int) -> None:
        response = requests.post(
            f'{self._harbor_url()}projects/{project_id}/members',
            json={
                'role_id': 2,
                'member_user': {'user_id': user_id},
            },
            auth=self._admin_auth(),
            timeout=self._timeout(),
        )
        if response.status_code not in {201, 409}:
            raise RuntimeError(f'配置个人镜像仓库权限失败：HTTP {response.status_code}')

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
            result['error'] = '镜像仓库查询失败'
        except Exception as exc:
            logger.warning('Unexpected Harbor project query failure for %s: %s', project_name, exc)
            result['error'] = '镜像仓库查询异常'

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
            return [], False, '镜像列表查询失败'

        if response.status_code == 404:
            return [], False, None

        if response.status_code in {401, 403}:
            logger.warning('Harbor repository auth failed for %s: HTTP %s', project_name, response.status_code)
            return [], False, '镜像仓库权限不足'

        if response.status_code != 200:
            logger.warning(
                'Harbor repository query failed for %s: HTTP %s %s',
                project_name,
                response.status_code,
                response.text,
            )
            return [], False, f'镜像列表查询失败：HTTP {response.status_code}'

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
