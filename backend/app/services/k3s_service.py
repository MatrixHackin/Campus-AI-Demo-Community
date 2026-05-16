from __future__ import annotations

import logging
import re

from app.core.config import Settings

logger = logging.getLogger(__name__)


class K3SService:
    """K3s 集群服务。

    当前只实现为 SSO 用户 emp_id 创建 namespace；后续 Pod / Service / PVC / NodePort
    等其他 K3s 能力也统一放到这个 service 中。
    namespace 命名规则：使用 emp_id，并转换为 Kubernetes DNS label 合法格式。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._core_v1 = None

    def namespace_for_emp_id(self, emp_id: str) -> str:
        namespace = re.sub(r'[^a-z0-9-]+', '-', emp_id.strip().lower()).strip('-')
        namespace = namespace[:63].rstrip('-')
        if not namespace or not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', namespace):
            raise ValueError(f'K3s namespace 名称不合法，emp_id={emp_id!r}')
        return namespace

    def ensure_user_namespace(self, emp_id: str | None) -> str | None:
        if not self.settings.k3s_namespace_sync_enabled:
            return None
        if not emp_id:
            logger.warning('跳过 K3s namespace 创建：缺少 emp_id')
            return None

        try:
            namespace = self.namespace_for_emp_id(emp_id)
        except ValueError as exc:
            logger.warning('跳过 K3s namespace 创建：%s', exc)
            return None

        try:
            self._core().create_namespace(self._namespace_body(namespace))
            logger.info('K3s namespace %s 创建成功', namespace)
        except self._api_exception_class() as exc:
            if exc.status == 409:
                logger.info('K3s namespace %s 已存在', namespace)
                return namespace
            logger.warning('K3s namespace %s 创建失败：%s', namespace, exc)
            return None
        except Exception as exc:
            logger.warning('K3s namespace %s 创建异常：%s', namespace, exc)
            return None
        return namespace

    def _core(self):
        if self._core_v1 is None:
            from kubernetes import client, config
            from kubernetes.config.config_exception import ConfigException

            try:
                config.load_incluster_config()
            except ConfigException:
                kubeconfig = self.settings.kubeconfig_path or self.settings.k3s_config_path
                config.load_kube_config(config_file=kubeconfig)
            self._core_v1 = client.CoreV1Api()
        return self._core_v1

    @staticmethod
    def _namespace_body(namespace: str):
        from kubernetes import client

        return client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))

    @staticmethod
    def _api_exception_class():
        from kubernetes.client.rest import ApiException

        return ApiException
