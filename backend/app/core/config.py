from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env', 'backend/.env'), env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Campus AI API'
    app_env: str = 'development'
    app_host: str = '0.0.0.0'
    app_port: int = 8000

    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['http://localhost:5173', 'http://127.0.0.1:5173']
    )
    cors_origin_regex: str | None = (
        r'^https?://('
        r'localhost|127\.0\.0\.1|'
        r'10(?:\.\d{1,3}){3}|'
        r'192\.168(?:\.\d{1,3}){2}|'
        r'172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}'
        r')(?::\d+)?$'
    )

    auth_backend: str = 'demo'
    demo_username: str = 'admin'
    demo_password: str = 'admin123'
    demo_display_name: str = 'Campus Admin'
    demo_emp_id: str | None = None
    token_ttl_hours: int = 12

    mysql_host: str = '127.0.0.1'
    mysql_port: int = 3306
    mysql_user: str = 'campusai'
    mysql_password: str = ''
    mysql_database: str = 'campus_ai'
    mysql_charset: str = 'utf8mb4'
    mysql_user_table: str = 'users'

    session_cookie_name: str = 'campus_ai_session'
    session_cookie_secure: bool = True
    session_cookie_samesite: str = 'lax'

    sso_domain: str = 'https://devsso.hkust-gz.edu.cn'
    sso_client_id: str = ''
    sso_client_secret: str = ''
    sso_redirect_uri: str = 'https://localhost:8080/signin-oidc'
    sso_post_logout_redirect_uri: str = 'https://localhost:8080/signout-callback'
    sso_scope: str = 'openid profile'
    sso_user_persistence_enabled: bool = True
    sso_user_table: str = 'sso_users'

    harbor_url: str = ''
    harbor_registry: str = 'gpunion2.io'
    harbor_admin_username: str = ''
    harbor_admin_password: str = ''
    harbor_user_project_suffix: str = '-repo'
    harbor_public_project: str = 'dev'
    harbor_request_timeout_seconds: int = 10

    user_max_storage: int = 10

    kubeconfig_path: str | None = None
    k3s_config_path: str = '/etc/rancher/k3s/k3s.yaml'
    k3s_devbox_image: str = 'gpunion2.io/dev/devbox:latest'
    k3s_devbox_cpu: str = '2'
    k3s_devbox_memory: str = '4Gi'
    k3s_devbox_command: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['/bin/sh', '-c', 'sleep infinity']
    )
    k3s_devbox_dns_nameservers: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['10.90.63.2', '10.90.63.3', '8.8.8.8']
    )
    k3s_apps_host: str = 'gpunion.hkust-gz.edu.cn'
    k3s_apps_path_prefix: str = '/apps'
    k3s_apps_public_base_url: str = 'https://gpunion.hkust-gz.edu.cn/apps'

    ssh_gateway_enabled: bool = True
    ssh_gateway_host: str = '0.0.0.0'
    ssh_gateway_port: int = 2222
    ssh_gateway_public_host: str = '10.120.17.138'
    ssh_gateway_host_key_path: str | None = None
    webssh_public_path_prefix: str = '/ssh'

    published_cover_storage_dir: str = 'static/covers'
    published_cover_public_prefix: str = '/api/static/covers'
    published_cover_max_bytes: int = 1024 * 1024

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator('cors_origin_regex', mode='before')
    @classmethod
    def parse_cors_origin_regex(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator('harbor_url', mode='before')
    @classmethod
    def normalize_harbor_url(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value.rstrip('/') + '/' if value else ''
        return value

    @field_validator('k3s_devbox_command', mode='before')
    @classmethod
    def parse_k3s_devbox_command(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator('k3s_devbox_dns_nameservers', mode='before')
    @classmethod
    def parse_k3s_devbox_dns_nameservers(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator(
        'k3s_apps_path_prefix',
        'k3s_apps_public_base_url',
        'webssh_public_path_prefix',
        'published_cover_public_prefix',
        mode='before',
    )
    @classmethod
    def normalize_k3s_apps_paths(cls, value):
        if isinstance(value, str):
            return value.strip().rstrip('/') or value
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
