"""Compatibility layer for GPUnion2-style imports.

新项目统一从 app.core.config.Settings 读取配置；此模块只保留旧代码中可能引用的
K3SConfig/StorageConfig 名称，避免再维护一份独立配置。
"""

from app.core.config import get_settings

_settings = get_settings()


class K3SConfig:
    K3S_CONFIG_PATH = _settings.kubeconfig_path or _settings.k3s_config_path


class StorageConfig:
    USER_MAX_STORAGE = _settings.user_max_storage
