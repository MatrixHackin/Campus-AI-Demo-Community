from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

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

    mock_kubernetes: bool = True
    kubernetes_namespace: str = 'campus-sandbox'
    kubeconfig_path: str | None = None
    default_sandbox_image: str = 'python:3.11-slim'
    default_sandbox_command: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['/bin/sh', '-c', 'sleep infinity']
    )

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
