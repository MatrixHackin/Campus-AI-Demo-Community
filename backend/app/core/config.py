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
    admin_usernames: Annotated[List[str], NoDecode] = Field(default_factory=lambda: ['admin'])

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

    sso_domain: str = 'https://sso.hkust-gz.edu.cn'
    sso_client_id: str = ''
    sso_client_secret: str = ''
    sso_redirect_uri: str = 'https://localhost:8080/signin-oidc'
    sso_post_logout_redirect_uri: str = 'https://localhost:8080/signout-callback'
    sso_scope: str = 'openid profile'
    sso_user_persistence_enabled: bool = True
    sso_user_table: str = 'sso_users'
    internal_api_token: str = ''

    harbor_url: str = ''
    harbor_registry: str = 'gpunion2.io'
    harbor_admin_username: str = ''
    harbor_admin_password: str = ''
    harbor_user_default_password: str = 'Habor!123'
    harbor_user_default_storage_quota: int = 50 * 1024 * 1024 * 1024
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
    k3s_commit_nerdctl_image: str = 'gpunion2.io/library/nerdctl:latest'
    k3s_commit_host_containerd_socket: str = '/run/k3s/containerd/containerd.sock'
    k3s_commit_containerd_socket: str = '/run/containerd/containerd.sock'
    k3s_commit_insecure_registry: bool = True
    k3s_commit_push_registry: str = ''
    k3s_apps_host: str = 'gpunion.hkust-gz.edu.cn'
    k3s_apps_path_prefix: str = '/apps'
    k3s_apps_public_base_url: str = 'https://gpunion.hkust-gz.edu.cn/apps'
    k3s_user_workspace_enabled: bool = True
    k3s_user_workspace_pvc_name: str = 'user-workspace'
    k3s_user_workspace_storage_class: str = 'longhorn'
    k3s_user_workspace_size: str = '64Gi'
    k3s_user_workspace_access_mode: str = 'ReadWriteMany'
    k3s_user_workspace_mount_path: str = '/mydata'
    k3s_network_policy_enabled: bool = True
    k3s_network_policy_public_web_egress_enabled: bool = True
    k3s_network_policy_public_web_except_cidrs: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: [
            '10.0.0.0/8',
            '172.16.0.0/12',
            '192.168.0.0/16',
            '100.64.0.0/10',
            '169.254.0.0/16',
        ]
    )
    k3s_network_policy_traefik_namespace: str = 'kube-system'
    k3s_network_policy_traefik_pod_labels: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['app.kubernetes.io/name=traefik']
    )
    k3s_network_policy_coredns_namespace: str = 'kube-system'
    k3s_network_policy_coredns_pod_labels: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['k8s-app=kube-dns']
    )
    k3s_network_policy_ssh_gateway_namespace: str = 'campus-ai-system'
    k3s_network_policy_ssh_gateway_pod_labels: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['app=ssh-gateway']
    )
    k3s_network_policy_internal_allow_rules: Annotated[List[str], NoDecode] = Field(default_factory=list)

    ssh_gateway_enabled: bool = True
    ssh_gateway_host: str = '0.0.0.0'
    ssh_gateway_port: int = 2222
    ssh_gateway_public_host: str = '10.120.17.138'
    ssh_gateway_host_key_path: str | None = '.run/ssh_gateway_host_key'
    ssh_gateway_target_mode: str = 'port_forward'
    ssh_gateway_resolver_mode: str = 'local'
    ssh_gateway_control_plane_base_url: str = 'http://127.0.0.1:8001'
    ssh_gateway_control_plane_internal_token: str = ''
    ssh_gateway_control_plane_timeout_seconds: float = 5.0
    webssh_public_path_prefix: str = '/ssh'

    published_cover_storage_dir: str = 'static/covers'
    published_cover_public_prefix: str = '/api/static/covers'
    published_cover_max_bytes: int = 1024 * 1024
    app_publish_review_policy: str = 'no_review'
    responsibility_ack_version: str = '2026-05-31'

    prometheus_url: str = 'http://10.43.146.195:9090'
    prometheus_query_timeout_seconds: int = 5
    prometheus_retention_seconds: int = 10 * 24 * 60 * 60
    prometheus_query_range_max_points: int = 240
    prometheus_query_range_min_step_seconds: int = 60
    prometheus_trend_step_seconds: int = 30

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

    @field_validator('admin_usernames', mode='before')
    @classmethod
    def parse_admin_usernames(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator('app_publish_review_policy', mode='before')
    @classmethod
    def normalize_app_publish_review_policy(cls, value):
        if isinstance(value, str):
            value = value.strip().lower().replace('-', '_')
            if value in {'none', 'off', 'disabled'}:
                return 'no_review'
            if value in {'all', 'required', 'require'}:
                return 'require_review'
            return value
        return value

    @field_validator('ssh_gateway_target_mode', mode='before')
    @classmethod
    def normalize_ssh_gateway_target_mode(cls, value):
        if isinstance(value, str):
            value = value.strip().lower().replace('-', '_')
            if value == 'portforward':
                value = 'port_forward'
        return value

    @field_validator('ssh_gateway_resolver_mode', mode='before')
    @classmethod
    def normalize_ssh_gateway_resolver_mode(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        'k3s_network_policy_public_web_except_cidrs',
        'k3s_network_policy_traefik_pod_labels',
        'k3s_network_policy_coredns_pod_labels',
        'k3s_network_policy_ssh_gateway_pod_labels',
        'k3s_network_policy_internal_allow_rules',
        mode='before',
    )
    @classmethod
    def parse_k3s_network_policy_lists(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator(
        'k3s_apps_path_prefix',
        'k3s_apps_public_base_url',
        'webssh_public_path_prefix',
        'published_cover_public_prefix',
        'ssh_gateway_control_plane_base_url',
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
