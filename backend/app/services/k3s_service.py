from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)


class K3SService:
    """K3s 集群服务。

    当前在用户申请容器时确保 emp_id 对应 namespace 存在，并创建默认 devbox Pod。
    后续 Service / PVC / NodePort 等其他 K3s 能力也统一放到这个 service 中。
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

    def create_devbox_container(self, emp_id: str | None) -> dict[str, Any]:
        """在 emp_id namespace 下创建一个默认 devbox 容器 Pod。

        仅创建 Pod；不创建 Kubernetes Service / NodePort / PVC。
        """
        namespace = self._ensure_user_namespace_or_raise(emp_id)

        pod_name = f'campus-devbox-{uuid.uuid4().hex[:8]}'
        pod = self._devbox_pod_body(pod_name=pod_name, namespace=namespace, emp_id=emp_id or '')
        try:
            self._core().create_namespaced_pod(namespace=namespace, body=pod)
        except self._api_exception_class() as exc:
            logger.warning('K3s devbox pod %s 创建失败：%s', pod_name, exc)
            raise RuntimeError(f'创建容器失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('K3s devbox pod %s 创建异常：%s', pod_name, exc)
            raise RuntimeError(f'创建容器失败：{exc}') from exc

        return {
            'pod_name': pod_name,
            'namespace': namespace,
            'image': self.settings.k3s_devbox_image,
            'cpu': self.settings.k3s_devbox_cpu,
            'memory': self.settings.k3s_devbox_memory,
            'status': 'creating',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

    def list_user_containers(self, emp_id: str | None) -> dict[str, Any]:
        """查询 emp_id 对应 namespace 下的 Pod 列表。

        查询操作不会创建 namespace；namespace 不存在时返回空列表。
        """
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法查询容器')

        try:
            namespace = self.namespace_for_emp_id(emp_id)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        try:
            pods = self._core().list_namespaced_pod(namespace=namespace).items
        except self._api_exception_class() as exc:
            if exc.status == 404:
                return {
                    'namespace': namespace,
                    'containers': [],
                }
            logger.warning('K3s namespace %s 容器查询失败：%s', namespace, exc)
            raise RuntimeError(f'查询容器失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('K3s namespace %s 容器查询异常：%s', namespace, exc)
            raise RuntimeError(f'查询容器失败：{exc}') from exc

        return {
            'namespace': namespace,
            'containers': [self._container_item_from_pod(pod) for pod in pods],
        }

    def _ensure_user_namespace_or_raise(self, emp_id: str | None) -> str:
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法创建 namespace')

        try:
            namespace = self.namespace_for_emp_id(emp_id)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        core_v1 = self._core()
        try:
            core_v1.read_namespace(name=namespace)
            logger.info('K3s namespace %s 已存在', namespace)
            return namespace
        except self._api_exception_class() as exc:
            if exc.status != 404:
                logger.warning('K3s namespace %s 查询失败：%s', namespace, exc)
                raise RuntimeError(f'查询 namespace 失败：{exc.reason or exc.status}') from exc

        try:
            core_v1.create_namespace(self._namespace_body(namespace, emp_id))
            logger.info('K3s namespace %s 创建成功', namespace)
            return namespace
        except self._api_exception_class() as exc:
            if exc.status == 409:
                logger.info('K3s namespace %s 已存在', namespace)
                return namespace
            logger.warning('K3s namespace %s 创建失败：%s', namespace, exc)
            raise RuntimeError(f'创建 namespace 失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('K3s namespace %s 创建异常：%s', namespace, exc)
            raise RuntimeError(f'创建 namespace 失败：{exc}') from exc

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
    def _namespace_body(namespace: str, emp_id: str | None = None):
        from kubernetes import client

        return client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=namespace,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/owner-namespace': namespace,
                },
                annotations={
                    'campus-ai/owner-emp-id': emp_id or '',
                },
            )
        )

    def _devbox_pod_body(self, pod_name: str, namespace: str, emp_id: str):
        from kubernetes import client

        resource_value = {
            'cpu': self.settings.k3s_devbox_cpu,
            'memory': self.settings.k3s_devbox_memory,
        }
        return client.V1Pod(
            api_version='v1',
            kind='Pod',
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    'app': 'campus-ai-devbox',
                    'campus-ai/owner-namespace': namespace,
                },
                annotations={
                    'campus-ai/owner-emp-id': emp_id,
                },
            ),
            spec=client.V1PodSpec(
                restart_policy='Never',
                containers=[
                    client.V1Container(
                        name='devbox',
                        image=self.settings.k3s_devbox_image,
                        command=self.settings.k3s_devbox_command,
                        resources=client.V1ResourceRequirements(
                            requests=resource_value,
                            limits=resource_value,
                        ),
                    )
                ],
            ),
        )

    @staticmethod
    def _container_item_from_pod(pod) -> dict[str, str]:
        containers = pod.spec.containers if pod.spec and pod.spec.containers else []
        image = containers[0].image if containers else ''

        status = pod.status.phase if pod.status and pod.status.phase else 'Unknown'
        if pod.metadata and pod.metadata.deletion_timestamp:
            status = 'Terminating'

        return {
            'name': pod.metadata.name if pod.metadata else '',
            'image': image,
            'status': status,
        }

    @staticmethod
    def _api_exception_class():
        from kubernetes.client.rest import ApiException

        return ApiException
