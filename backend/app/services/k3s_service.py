from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.services.container_repository import ContainerRepository

logger = logging.getLogger(__name__)


class K3SService:
    """K3s 集群服务。

    当前在用户申请容器时确保 emp_id 对应 namespace 存在，并创建默认 devbox Pod。
    后续 Service / PVC / NodePort 等其他 K3s 能力也统一放到这个 service 中。
    namespace 命名规则：使用 emp_id，并转换为 Kubernetes DNS label 合法格式。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.container_repository = ContainerRepository(settings)
        self._core_v1 = None
        self._networking_v1 = None

    def namespace_for_emp_id(self, emp_id: str) -> str:
        namespace = re.sub(r'[^a-z0-9-]+', '-', emp_id.strip().lower()).strip('-')
        namespace = namespace[:63].rstrip('-')
        if not namespace or not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', namespace):
            raise ValueError(f'K3s namespace 名称不合法，emp_id={emp_id!r}')
        return namespace

    def app_url(self, app_name: str) -> str:
        return f'{self.settings.k3s_apps_public_base_url}/{app_name}'

    def normalize_app_name(self, app_name: str) -> str:
        normalized = app_name.strip().lower()
        if len(normalized) > 40:
            raise ValueError('应用名称最多 40 个字符')
        if not normalized or not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', normalized):
            raise ValueError('应用名称只允许小写字母、数字和中划线，且必须以字母或数字开头结尾')
        if normalized in {'api', 'auth', 'login', 'dashboard', 'manual', 'assets', 'signin-oidc', 'signout-callback'}:
            raise ValueError('该应用名称为系统保留名称，请更换')
        return normalized

    def check_app_name_availability(self, app_name: str) -> dict[str, Any]:
        normalized = self.normalize_app_name(app_name)
        available = (
            not self.container_repository.app_name_exists(normalized)
            and self._is_k8s_app_name_available(normalized)
        )
        return {
            'app_name': normalized,
            'available': available,
            'url': self.app_url(normalized),
            'message': None if available else '该应用名称已被使用',
        }

    def create_devbox_container(
        self,
        emp_id: str | None,
        username: str,
        app_name: str,
        connection_password: str,
    ) -> dict[str, Any]:
        """在 emp_id namespace 下创建一个默认 devbox 容器 Pod。

        同时创建 ClusterIP Service 和 Traefik Ingress，将 3000 端口应用暴露到
        /apps/{app_name}。连接密码先保存为 Kubernetes Secret，后续用于 SSH。
        """
        normalized_app_name = self.normalize_app_name(app_name)
        if not connection_password or len(connection_password.strip()) < 6:
            raise ValueError('连接密码至少需要 6 位')
        if self.container_repository.app_name_exists(normalized_app_name):
            raise FileExistsError('该应用名称已被使用')
        if not self._is_k8s_app_name_available(normalized_app_name):
            raise FileExistsError('该应用名称对应的 Kubernetes 资源已存在')

        namespace = self._ensure_user_namespace_or_raise(emp_id)
        pod_name = f'campus-devbox-{uuid.uuid4().hex[:8]}'
        pod = self._devbox_pod_body(
            pod_name=pod_name,
            namespace=namespace,
            emp_id=emp_id or '',
            app_name=normalized_app_name,
        )
        try:
            self.container_repository.create_container_record(
                pod_name=pod_name,
                app_name=normalized_app_name,
                username=username,
                password=connection_password,
            )
            self._core().create_namespaced_secret(
                namespace=namespace,
                body=self._connection_secret_body(normalized_app_name, connection_password),
            )
            self._core().create_namespaced_pod(namespace=namespace, body=pod)
            self._core().create_namespaced_service(
                namespace=namespace,
                body=self._app_service_body(normalized_app_name),
            )
            self._networking().create_namespaced_ingress(
                namespace=namespace,
                body=self._app_ingress_body(normalized_app_name),
            )
        except self._api_exception_class() as exc:
            self._rollback_app_creation(namespace, pod_name, normalized_app_name)
            if exc.status == 409:
                raise FileExistsError('该应用名称对应的 Kubernetes 资源已存在') from exc
            logger.warning('K3s devbox 应用 %s 创建失败：%s', normalized_app_name, exc)
            raise RuntimeError(f'创建容器失败：{exc.reason or exc.status}') from exc
        except FileExistsError:
            raise
        except Exception as exc:
            self._rollback_app_creation(namespace, pod_name, normalized_app_name)
            logger.warning('K3s devbox 应用 %s 创建异常：%s', normalized_app_name, exc)
            raise RuntimeError(f'创建容器失败：{exc}') from exc

        return {
            'pod_name': pod_name,
            'namespace': namespace,
            'app_name': normalized_app_name,
            'url': self.app_url(normalized_app_name),
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

    def _networking(self):
        if self._networking_v1 is None:
            from kubernetes import client

            self._core()
            self._networking_v1 = client.NetworkingV1Api()
        return self._networking_v1

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

    def _devbox_pod_body(self, pod_name: str, namespace: str, emp_id: str, app_name: str):
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
                    'campus-ai/app-name': app_name,
                    'campus-ai/owner-namespace': namespace,
                },
                annotations={
                    'campus-ai/owner-emp-id': emp_id,
                    'campus-ai/public-url': self.app_url(app_name),
                },
            ),
            spec=client.V1PodSpec(
                restart_policy='Never',
                containers=[
                    client.V1Container(
                        name='devbox',
                        image=self.settings.k3s_devbox_image,
                        command=self.settings.k3s_devbox_command,
                        ports=[
                            client.V1ContainerPort(
                                name='http',
                                container_port=3000,
                            )
                        ],
                        resources=client.V1ResourceRequirements(
                            requests=resource_value,
                            limits=resource_value,
                        ),
                    )
                ],
            ),
        )

    def _connection_secret_body(self, app_name: str, connection_password: str):
        from kubernetes import client

        return client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=f'{app_name}-connection',
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/app-name': app_name,
                },
            ),
            string_data={
                'connection_password': connection_password,
            },
            type='Opaque',
        )

    def _app_service_body(self, app_name: str):
        from kubernetes import client

        return client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f'{app_name}-svc',
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/app-name': app_name,
                },
            ),
            spec=client.V1ServiceSpec(
                type='ClusterIP',
                selector={
                    'campus-ai/app-name': app_name,
                },
                ports=[
                    client.V1ServicePort(
                        name='http',
                        port=80,
                        target_port=3000,
                    )
                ],
            ),
        )

    def _app_ingress_body(self, app_name: str):
        from kubernetes import client

        path = f'{self.settings.k3s_apps_path_prefix}/{app_name}'
        return client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=app_name,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/app-name': app_name,
                },
            ),
            spec=client.V1IngressSpec(
                ingress_class_name='traefik',
                rules=[
                    client.V1IngressRule(
                        host=self.settings.k3s_apps_host,
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path=path,
                                    path_type='Prefix',
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=f'{app_name}-svc',
                                            port=client.V1ServiceBackendPort(number=80),
                                        )
                                    ),
                                )
                            ]
                        ),
                    )
                ],
            ),
        )

    def _is_k8s_app_name_available(self, app_name: str) -> bool:
        label_selector = f'campus-ai/app-name={app_name}'
        try:
            pods = self._core().list_pod_for_all_namespaces(label_selector=label_selector).items
            if pods:
                return False

            services = self._core().list_service_for_all_namespaces(label_selector=label_selector).items
            if services:
                return False

            ingresses = self._networking().list_ingress_for_all_namespaces(label_selector=label_selector).items
            if ingresses:
                return False

            expected_path = f'{self.settings.k3s_apps_path_prefix}/{app_name}'
            all_ingresses = self._networking().list_ingress_for_all_namespaces().items
            for ingress in all_ingresses:
                for rule in ingress.spec.rules or []:
                    for path in rule.http.paths if rule.http else []:
                        if path.path == expected_path:
                            return False
        except self._api_exception_class() as exc:
            logger.warning('K3s 应用名称 %s 可用性检查失败：%s', app_name, exc)
            raise RuntimeError(f'检查应用名称失败：{exc.reason or exc.status}') from exc
        return True

    def _rollback_app_creation(self, namespace: str, pod_name: str, app_name: str) -> None:
        """尽力回滚部分创建成功的资源，避免失败申请占用 app_name。"""
        api_exception = self._api_exception_class()
        cleanup_steps = (
            lambda: self._networking().delete_namespaced_ingress(name=app_name, namespace=namespace),
            lambda: self._core().delete_namespaced_service(name=f'{app_name}-svc', namespace=namespace),
            lambda: self._core().delete_namespaced_secret(name=f'{app_name}-connection', namespace=namespace),
            lambda: self._core().delete_namespaced_pod(name=pod_name, namespace=namespace),
            lambda: self.container_repository.delete_container_record(pod_name=pod_name),
        )
        for cleanup in cleanup_steps:
            try:
                cleanup()
            except api_exception as exc:
                if exc.status != 404:
                    logger.warning('K3s devbox 应用 %s 回滚部分资源失败：%s', app_name, exc)
            except Exception as exc:
                logger.warning('K3s devbox 应用 %s 回滚部分资源异常：%s', app_name, exc)

    @staticmethod
    def _container_item_from_pod(pod) -> dict[str, Any]:
        containers = pod.spec.containers if pod.spec and pod.spec.containers else []
        image = containers[0].image if containers else ''
        labels = pod.metadata.labels if pod.metadata and pod.metadata.labels else {}
        annotations = pod.metadata.annotations if pod.metadata and pod.metadata.annotations else {}
        app_name = labels.get('campus-ai/app-name')

        status = pod.status.phase if pod.status and pod.status.phase else 'Unknown'
        if pod.metadata and pod.metadata.deletion_timestamp:
            status = 'Terminating'

        return {
            'name': pod.metadata.name if pod.metadata else '',
            'image': image,
            'status': status,
            'app_name': app_name,
            'url': annotations.get('campus-ai/public-url'),
        }

    @staticmethod
    def _api_exception_class():
        from kubernetes.client.rest import ApiException

        return ApiException
