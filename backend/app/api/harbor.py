from __future__ import annotations

from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import Settings, get_settings


USER_DEFAULT_PASSWORD = get_settings().harbor_user_default_password
USER_DEFAULT_STORAGE_QUOTA = get_settings().harbor_user_default_storage_quota


def _settings() -> Settings:
    return get_settings()


def _harbor_url() -> str:
    return _settings().harbor_url.rstrip('/') + '/'


def _admin_auth() -> HTTPBasicAuth:
    settings = _settings()
    if not settings.harbor_admin_username or not settings.harbor_admin_password:
        raise RuntimeError('Harbor 管理员账号未配置，请设置 HARBOR_ADMIN_USERNAME/HARBOR_ADMIN_PASSWORD')
    return HTTPBasicAuth(settings.harbor_admin_username, settings.harbor_admin_password)


def _user_project_name(user_email: str) -> str:
    return f"{user_email.replace('@', '-at-').replace('.', '-dot-')}-repo"


def _get_repo_tags(project_name: str, repo_name: str) -> list[str]:
    tags: list[str] = []
    try:
        encoded_repo_name = quote(repo_name, safe='')
        artifacts_resp = requests.get(
            f'{_harbor_url()}projects/{project_name}/repositories/{encoded_repo_name}/artifacts',
            params={'page_size': 100, 'with_tag': 'true'},
            auth=_admin_auth(),
            timeout=10,
        )
        if artifacts_resp.status_code != 200:
            return tags

        seen = set()
        for artifact in artifacts_resp.json():
            for tag in artifact.get('tags') or []:
                tag_name = tag.get('name')
                if tag_name and tag_name not in seen:
                    seen.add(tag_name)
                    tags.append(tag_name)
    except Exception as exc:
        print(f'Error fetching tags for {project_name}/{repo_name}: {exc}')
    return tags


def _get_user_id(target_username: str) -> int:
    resp = requests.get(
        f'{_harbor_url()}users',
        params={'username': target_username},
        auth=_admin_auth(),
        timeout=10,
    )
    resp.raise_for_status()
    users = resp.json()
    if not users:
        raise ValueError(f'User {target_username} not found')
    return users[0]['user_id']


def _get_project_id(project_name: str) -> int:
    resp = requests.get(
        f'{_harbor_url()}projects',
        params={'name': project_name},
        auth=_admin_auth(),
        timeout=10,
    )
    resp.raise_for_status()
    projects = resp.json()
    if not projects:
        raise ValueError(f'Project {project_name} not found')
    return projects[0]['project_id']


def register_user_with_repo(new_username: str, new_password: str | None = None, email: str | None = None) -> dict:
    """注册 Harbor 用户，并为其创建一个私有项目。"""
    settings = _settings()
    email = email or new_username
    new_password = new_password or settings.harbor_user_default_password
    if not new_password:
        raise RuntimeError('Harbor 默认用户密码未配置，请设置 HARBOR_USER_DEFAULT_PASSWORD')

    user_payload = {
        'username': new_username,
        'password': new_password,
        'email': email,
        'realname': new_username,
        'comment': 'auto-created by Campus AI',
    }
    user_resp = requests.post(f'{_harbor_url()}users', json=user_payload, auth=_admin_auth(), timeout=10)
    if user_resp.status_code not in (201, 409):
        raise RuntimeError(f'Failed to create user: {user_resp.status_code} {user_resp.text}')
    user_id = _get_user_id(new_username)

    project_name = _user_project_name(new_username)
    project_payload = {
        'project_name': project_name,
        'metadata': {'public': 'false'},
        'storage_limit': settings.harbor_user_default_storage_quota,
    }
    project_resp = requests.post(f'{_harbor_url()}projects', json=project_payload, auth=_admin_auth(), timeout=10)
    if project_resp.status_code not in (201, 409):
        raise RuntimeError(f'Failed to create project: {project_resp.status_code} {project_resp.text}')
    project_id = _get_project_id(project_name)

    member_payload = {
        'role_id': 2,  # developer
        'member_user': {'user_id': user_id},
    }
    member_resp = requests.post(
        f'{_harbor_url()}projects/{project_id}/members',
        json=member_payload,
        auth=_admin_auth(),
        timeout=10,
    )
    if member_resp.status_code not in (201, 409):
        raise RuntimeError(f'Failed to add member: {member_resp.status_code} {member_resp.text}')

    return {'user_id': user_id, 'project_id': project_id, 'project_name': project_name}


def delete_user_with_repo(target_username: str) -> dict:
    """删除 Harbor 用户及其专属私有项目。"""
    project_name = _user_project_name(target_username)
    project_deleted = False
    user_deleted = False
    project_error = None
    user_error = None

    try:
        project_id = _get_project_id(project_name)
        resp = requests.delete(f'{_harbor_url()}projects/{project_id}', auth=_admin_auth(), timeout=10)
        if resp.status_code in (200, 202, 204, 404):
            project_deleted = resp.status_code != 404
        else:
            project_error = f'Failed to delete project: {resp.status_code} {resp.text}'
    except ValueError:
        project_error = 'Project not found'
    except Exception as exc:
        project_error = str(exc)

    try:
        user_id = _get_user_id(target_username)
        resp = requests.delete(f'{_harbor_url()}users/{user_id}', auth=_admin_auth(), timeout=10)
        if resp.status_code in (200, 202, 204, 404):
            user_deleted = resp.status_code != 404
        else:
            user_error = f'Failed to delete user: {resp.status_code} {resp.text}'
    except ValueError:
        user_error = 'User not found'
    except Exception as exc:
        user_error = str(exc)

    return {
        'project_name': project_name,
        'project_deleted': project_deleted,
        'project_error': project_error,
        'user_deleted': user_deleted,
        'user_error': user_error,
    }


def get_proj_by_useremail(user_email: str, include_tags: bool = False) -> dict | None:
    """查询某个用户专属 Harbor 项目的配额和镜像仓库。"""
    project_name = _user_project_name(user_email)
    result = {
        'project_name': project_name,
        'quota': {'used': 0, 'limit': 0},
        'repos': [],
    }

    try:
        project_id = _get_project_id(project_name)
        summary_resp = requests.get(f'{_harbor_url()}projects/{project_id}/summary', auth=_admin_auth(), timeout=10)
        if summary_resp.status_code == 200:
            summary_data = summary_resp.json()
            if 'quota' in summary_data:
                result['quota']['used'] = summary_data['quota'].get('used', 0)
                result['quota']['limit'] = summary_data['quota'].get('hard', 0)

        repos_resp = requests.get(
            f'{_harbor_url()}projects/{project_name}/repositories',
            params={'page_size': 100},
            auth=_admin_auth(),
            timeout=10,
        )
        if repos_resp.status_code == 200:
            for repo in repos_resp.json():
                repo_name = repo['name'].split('/')[-1]
                repo_info = {
                    'name': repo_name,
                    'full_name': repo['name'],
                    'artifact_count': repo.get('artifact_count', 0),
                    'pull_count': repo.get('pull_count', 0),
                    'update_time': repo.get('update_time'),
                }
                if include_tags:
                    repo_info['tags'] = _get_repo_tags(project_name, repo_name)
                result['repos'].append(repo_info)
    except ValueError:
        return None
    except Exception as exc:
        print(f'Error fetching harbor info for {user_email}: {exc}')
        return None

    return result


def _get_project_repos(project_name: str, include_tags: bool = False) -> dict | None:
    result = {'project_name': project_name, 'repos': []}

    try:
        repos_resp = requests.get(
            f'{_harbor_url()}projects/{project_name}/repositories',
            params={'page_size': 100},
            auth=_admin_auth(),
            timeout=10,
        )
        if repos_resp.status_code != 200:
            print(f'Failed to fetch {project_name} repos: {repos_resp.status_code} {repos_resp.text}')
            return result

        for repo in repos_resp.json():
            repo_name = repo['name'].split('/')[-1]
            if repo_name == 'nerdctl':
                continue
            repo_info = {
                'name': repo_name,
                'full_name': repo['name'],
                'artifact_count': repo.get('artifact_count', 0),
                'pull_count': repo.get('pull_count', 0),
                'update_time': repo.get('update_time'),
            }
            if include_tags:
                repo_info['tags'] = _get_repo_tags(project_name, repo_name)
            result['repos'].append(repo_info)
    except Exception as exc:
        print(f'Error fetching project {project_name} info: {exc}')
        return None

    return result


def get_public_proj(include_tags: bool = False) -> dict | None:
    return _get_project_repos(_settings().harbor_public_project, include_tags=include_tags)


def get_dev_proj(include_tags: bool = False) -> dict | None:
    return _get_project_repos(_settings().harbor_dev_project, include_tags=include_tags)


def delete_repo_with_reponame(project_name: str, repo_name: str) -> dict:
    repo_deleted = False
    repo_error = None

    try:
        encoded_repo_name = quote(repo_name, safe='')
        resp = requests.delete(
            f'{_harbor_url()}projects/{project_name}/repositories/{encoded_repo_name}',
            auth=_admin_auth(),
            timeout=10,
        )
        if resp.status_code in (200, 202, 204):
            repo_deleted = True
        elif resp.status_code == 404:
            repo_error = 'Repository not found'
        else:
            repo_error = f'Failed to delete repository: {resp.status_code} {resp.text}'
    except Exception as exc:
        repo_error = f'Error deleting repository: {exc}'

    return {
        'project_name': project_name,
        'repo_name': repo_name,
        'repo_deleted': repo_deleted,
        'repo_error': repo_error,
    }
