from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env', 'backend/.env'), env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Campus AI Sandbox API'
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

    # Kubernetes / K3s
    kubernetes_namespace: str = 'campus-sandbox'
    kubeconfig_path: str | None = None
    k3s_config_path: str = '/etc/rancher/k3s/k3s.yaml'
    sandbox_namespace_mode: str = 'shared'  # shared 或 user
    default_sandbox_image: str = 'python:3.11-slim'
    default_sandbox_command: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['/bin/sh', '-c', 'sleep infinity']
    )
    default_sandbox_username: str = 'user'
    default_sandbox_password: str = 'password'
    default_sandbox_gpu_count: int = 0
    default_sandbox_cpu: str = '4'
    default_sandbox_memory: str = '8Gi'
    default_sandbox_shm_size: str = '8Gi'
    gpu_cpu_per_card: int = 16
    gpu_memory_per_card_gi: int = 48
    gpu_shm_per_card_gi: int = 24
    nvidia_runtime_class_name: str = 'nvidia'
    ascend_image_name: str = 'gpunion2.io/cann'
    enable_sandbox_nodeport: bool = True
    sandbox_ssh_port: int = 22
    sandbox_wait_until_running: bool = False
    sandbox_wait_timeout_seconds: int = 120

    # Harbor. 账号和密码请通过 .env/环境变量配置，不要写入源码。
    harbor_url: str = 'http://10.120.17.137:5053/api/v2.0/'
    harbor_registry: str = 'gpunion2.io'
    harbor_admin_username: str = ''
    harbor_admin_password: str = ''
    harbor_user_default_password: str = ''
    harbor_user_default_storage_quota: int = 50 * 1024 * 1024 * 1024
    harbor_public_project: str = 'library'
    harbor_dev_project: str = 'dev'

    prometheus_url: str = 'http://10.43.146.195:9090'
    user_max_storage: float = 512.00

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

    @field_validator('default_sandbox_command', mode='before')
    @classmethod
    def parse_default_command(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator('sandbox_namespace_mode', mode='before')
    @classmethod
    def parse_namespace_mode(cls, value):
        value = (value or 'shared').strip().lower()
        return value if value in {'shared', 'user'} else 'shared'

    @field_validator('harbor_url', mode='before')
    @classmethod
    def normalize_harbor_url(cls, value):
        if isinstance(value, str) and value:
            return value.rstrip('/') + '/'
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
