from __future__ import annotations

import logging
import re
import shlex
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.core.config import Settings
from app.services.container_repository import ContainerRepository
from app.services.publication_repository import PublicationRepository

logger = logging.getLogger(__name__)

K8S_DNS_LABEL_PATTERN = re.compile(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?')
RESERVED_APP_NAMES = {
    'api',
    'assets',
    'auth',
    'dashboard',
    'login',
    'manual',
    'signin-oidc',
    'signout-callback',
}


class K3SService:
    """K3s 集群服务。

    当前在用户申请容器时确保 emp_id 对应 namespace 存在，并创建默认 devbox Pod。
    后续 Service / PVC / NodePort 等其他 K3s 能力也统一放到这个 service 中。
    namespace 命名规则：使用 emp_id，并转换为 Kubernetes DNS label 合法格式。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.container_repository = ContainerRepository(settings)
        self.publication_repository = PublicationRepository(settings)
        self._core_v1 = None
        self._networking_v1 = None

    def namespace_for_emp_id(self, emp_id: str) -> str:
        namespace = re.sub(r'[^a-z0-9-]+', '-', emp_id.strip().lower()).strip('-')
        namespace = namespace[:63].rstrip('-')
        if not namespace or not K8S_DNS_LABEL_PATTERN.fullmatch(namespace):
            raise ValueError(f'K3s namespace 名称不合法，emp_id={emp_id!r}')
        return namespace

    def app_url(self, app_name: str) -> str:
        return f'{self.settings.k3s_apps_public_base_url}/{app_name}'

    def webssh_url(self, app_name: str, ssh_username: str) -> str:
        encoded_app_name = quote(app_name, safe='')
        encoded_ssh_username = quote(ssh_username, safe='')
        return f'{self.settings.webssh_public_path_prefix}/{encoded_app_name}+{encoded_ssh_username}'

    def native_ssh_command(self, app_name: str, ssh_username: str) -> str:
        login_name = f'{ssh_username}+{app_name}'
        if not re.fullmatch(r'[A-Za-z0-9._+-]+', login_name):
            return (
                f'ssh -l {shlex.quote(login_name)} {self.settings.ssh_gateway_public_host} '
                f'-p {self.settings.ssh_gateway_port}'
            )
        return (
            f'ssh {login_name}@{self.settings.ssh_gateway_public_host} '
            f'-p {self.settings.ssh_gateway_port}'
        )

    def normalize_app_name(self, app_name: str) -> str:
        normalized = app_name.strip().lower()
        if len(normalized) > 40:
            raise ValueError('应用名称最多 40 个字符')
        if not normalized or not K8S_DNS_LABEL_PATTERN.fullmatch(normalized):
            raise ValueError('应用名称只允许小写字母、数字和中划线，且必须以字母或数字开头结尾')
        if normalized in RESERVED_APP_NAMES:
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
        ssh_service_name = f'{normalized_app_name}-ssh-svc'
        pod = self._devbox_pod_body(
            pod_name=pod_name,
            namespace=namespace,
            emp_id=emp_id or '',
            app_name=normalized_app_name,
            ssh_username=username,
        )
        try:
            self.container_repository.create_container_record(
                pod_name=pod_name,
                app_name=normalized_app_name,
                namespace=namespace,
                username=username,
                password=connection_password,
                ssh_username=username,
                ssh_service_name=ssh_service_name,
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
            self._core().create_namespaced_service(
                namespace=namespace,
                body=self._ssh_service_body(normalized_app_name),
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
            'ssh_username': username,
            'webssh_url': self.webssh_url(normalized_app_name, username),
            'native_ssh_command': self.native_ssh_command(normalized_app_name, username),
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

        containers = [self._container_item_from_pod(pod) for pod in pods]
        try:
            published_pod_names = self.publication_repository.get_published_pod_names(
                [container['name'] for container in containers if container.get('name')]
            )
            for container in containers:
                container['is_published'] = container.get('name') in published_pod_names
        except Exception as exc:
            logger.warning('查询容器发布状态失败：%s', exc)

        return {
            'namespace': namespace,
            'containers': containers,
        }

    def delete_user_container(self, emp_id: str | None, username: str, pod_name: str) -> dict[str, Any]:
        """删除当前用户 namespace 下的 Pod 及其配套 Secret/Service/Ingress/DB 记录。"""
        if not pod_name or not K8S_DNS_LABEL_PATTERN.fullmatch(pod_name):
            raise ValueError('Pod 名称不合法')
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法删除容器')

        try:
            namespace = self.namespace_for_emp_id(emp_id)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        record = self.container_repository.get_container_record(pod_name=pod_name)
        if record and record.get('username') and record['username'] != username:
            raise PermissionError('无权删除该容器')

        app_name = record.get('app_name') if record else None
        try:
            pod = self._core().read_namespaced_pod(name=pod_name, namespace=namespace)
            labels = pod.metadata.labels if pod.metadata and pod.metadata.labels else {}
            app_name = app_name or labels.get('campus-ai/app-name')
        except self._api_exception_class() as exc:
            if exc.status != 404:
                logger.warning('K3s Pod %s/%s 查询失败：%s', namespace, pod_name, exc)
                raise RuntimeError(f'查询容器失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('K3s Pod %s/%s 查询异常：%s', namespace, pod_name, exc)
            raise RuntimeError(f'查询容器失败：{exc}') from exc

        self._delete_app_resources(namespace=namespace, pod_name=pod_name, app_name=app_name, strict=True)
        try:
            self.publication_repository.delete_by_pod_name(pod_name)
        except Exception as exc:
            logger.warning('删除容器 %s 时取消发布记录失败，跳过：%s', pod_name, exc)
        self.container_repository.delete_container_record(pod_name=pod_name)
        return {
            'pod_name': pod_name,
            'namespace': namespace,
            'app_name': app_name,
            'status': 'deleting',
        }

    def get_ssh_target(
        self,
        app_name: str,
        ssh_username: str,
        owner_username: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """查询并校验 app 对应的 SSH Service 目标。"""
        normalized_app_name = self.normalize_app_name(app_name)
        record = self.container_repository.get_container_record_by_app_name(app_name=normalized_app_name)
        if not record:
            raise FileNotFoundError('未找到应用对应的容器记录')

        record_ssh_username = record.get('ssh_username') or record.get('username')
        if record_ssh_username != ssh_username:
            raise PermissionError('SSH 用户名与应用记录不匹配')
        if owner_username is not None and record.get('username') != owner_username:
            raise PermissionError('无权访问该应用 SSH')
        if password is not None and record.get('password') != password:
            raise PermissionError('SSH 密码错误')

        namespace = record.get('namespace')
        ssh_service_name = record.get('ssh_service_name') or f'{normalized_app_name}-ssh-svc'
        if not namespace:
            raise RuntimeError('容器记录缺少 namespace，无法连接 SSH')

        try:
            service = self._core().read_namespaced_service(name=ssh_service_name, namespace=namespace)
        except self._api_exception_class() as exc:
            if exc.status == 404:
                raise FileNotFoundError('未找到应用 SSH Service') from exc
            raise RuntimeError(f'查询 SSH Service 失败：{exc.reason or exc.status}') from exc

        cluster_ip = service.spec.cluster_ip if service.spec else None
        if not cluster_ip or cluster_ip == 'None':
            raise RuntimeError('SSH Service 缺少 ClusterIP')

        return {
            'app_name': normalized_app_name,
            'namespace': namespace,
            'pod_name': record.get('pod_name'),
            'ssh_username': record_ssh_username,
            'password': record.get('password'),
            'service_name': ssh_service_name,
            'host': cluster_ip,
            'port': 22,
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

    def _devbox_pod_body(self, pod_name: str, namespace: str, emp_id: str, app_name: str, ssh_username: str):
        from kubernetes import client

        resource_value = {
            'cpu': self.settings.k3s_devbox_cpu,
            'memory': self.settings.k3s_devbox_memory,
        }
        startup_script = self._devbox_startup_script()
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
                    'campus-ai/ssh-username': ssh_username,
                    'campus-ai/webssh-url': self.webssh_url(app_name, ssh_username),
                    'campus-ai/native-ssh-command': self.native_ssh_command(app_name, ssh_username),
                },
            ),
            spec=client.V1PodSpec(
                restart_policy='Never',
                dns_policy='None' if self.settings.k3s_devbox_dns_nameservers else 'ClusterFirst',
                dns_config=self._devbox_dns_config(),
                containers=[
                    client.V1Container(
                        name='devbox',
                        image=self.settings.k3s_devbox_image,
                        command=['/bin/bash', '-lc', startup_script],
                        env=[
                            client.V1EnvVar(name='USERNAME', value=ssh_username),
                            client.V1EnvVar(
                                name='PASSWORD',
                                value_from=client.V1EnvVarSource(
                                    secret_key_ref=client.V1SecretKeySelector(
                                        name=f'{app_name}-connection',
                                        key='connection_password',
                                    )
                                ),
                            ),
                        ],
                        ports=[
                            client.V1ContainerPort(
                                name='http',
                                container_port=3000,
                            ),
                            client.V1ContainerPort(
                                name='ssh',
                                container_port=22,
                            ),
                        ],
                        resources=client.V1ResourceRequirements(
                            requests=resource_value,
                            limits=resource_value,
                        ),
                    )
                ],
            ),
        )

    def _devbox_dns_config(self):
        if not self.settings.k3s_devbox_dns_nameservers:
            return None

        from kubernetes import client

        return client.V1PodDNSConfig(
            nameservers=self.settings.k3s_devbox_dns_nameservers,
            searches=[
                'svc.cluster.local',
                'cluster.local',
            ],
            options=[
                client.V1PodDNSConfigOption(name='ndots', value='2'),
            ],
        )

    def _devbox_startup_script(self) -> str:
        app_command = shlex.join(self.settings.k3s_devbox_command)
        return (
            'set -e; '
            'if id "$USERNAME" >/dev/null 2>&1; then '
            '  echo "$USERNAME:$PASSWORD" | chpasswd; '
            '  usermod -s /bin/bash "$USERNAME" 2>/dev/null || true; '
            'else '
            '  useradd -m -s /bin/bash "$USERNAME"; '
            '  echo "$USERNAME:$PASSWORD" | chpasswd; '
            'fi; '
            'mkdir -p "/home/$USERNAME"; '
            'chown "$USERNAME:$USERNAME" "/home/$USERNAME" 2>/dev/null || true; '
            'usermod -aG sudo "$USERNAME" 2>/dev/null || true; '
            'ssh-keygen -A; '
            'mkdir -p /run/sshd /var/run/sshd; '
            'if [ -f /etc/ssh/sshd_config ]; then '
            '  sed -i "s/^#\\?PasswordAuthentication .*/PasswordAuthentication yes/" /etc/ssh/sshd_config || true; '
            '  grep -q "^PasswordAuthentication " /etc/ssh/sshd_config || printf "\\nPasswordAuthentication yes\\n" >> /etc/ssh/sshd_config; '
            '  sed -i "s/^#\\?UsePAM .*/UsePAM no/" /etc/ssh/sshd_config || true; '
            '  grep -q "^UsePAM " /etc/ssh/sshd_config || printf "UsePAM no\\n" >> /etc/ssh/sshd_config; '
            'fi; '
            '/usr/sbin/sshd -D -e & '
            'SSHD_PID=$!; '
            f'exec {app_command}'
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

    def _ssh_service_body(self, app_name: str):
        from kubernetes import client

        return client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f'{app_name}-ssh-svc',
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
                        name='ssh',
                        port=22,
                        target_port=22,
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
        self._delete_app_resources(namespace=namespace, pod_name=pod_name, app_name=app_name)
        self.container_repository.delete_container_record(pod_name=pod_name, suppress_errors=True)

    def _delete_app_resources(
        self,
        namespace: str,
        pod_name: str,
        app_name: str | None,
        strict: bool = False,
    ) -> None:
        """删除应用相关 K8s 资源；404 视为已经删除。

        strict=False 用于创建失败回滚，会尽力清理并记录日志；
        strict=True 用于用户主动删除，若 K8s 删除失败则阻止删除数据库记录，避免后台资源孤儿化。
        """
        api_exception = self._api_exception_class()
        errors: list[str] = []
        cleanup_steps = []
        if app_name:
            cleanup_steps.extend(
                [
                    (
                        f'ingress/{app_name}',
                        lambda: self._networking().delete_namespaced_ingress(name=app_name, namespace=namespace),
                    ),
                    (
                        f'service/{app_name}-svc',
                        lambda: self._core().delete_namespaced_service(name=f'{app_name}-svc', namespace=namespace),
                    ),
                    (
                        f'service/{app_name}-ssh-svc',
                        lambda: self._core().delete_namespaced_service(name=f'{app_name}-ssh-svc', namespace=namespace),
                    ),
                    (
                        f'secret/{app_name}-connection',
                        lambda: self._core().delete_namespaced_secret(name=f'{app_name}-connection', namespace=namespace),
                    ),
                ]
            )
        cleanup_steps.append(
            (
                f'pod/{pod_name}',
                lambda: self._core().delete_namespaced_pod(name=pod_name, namespace=namespace),
            )
        )

        for resource_name, cleanup in cleanup_steps:
            try:
                cleanup()
            except api_exception as exc:
                if exc.status != 404:
                    message = f'{resource_name}: {exc.reason or exc.status}'
                    errors.append(message)
                    logger.warning('K3s devbox 应用 %s 删除资源 %s 失败：%s', app_name or pod_name, resource_name, exc)
            except Exception as exc:
                message = f'{resource_name}: {exc}'
                errors.append(message)
                logger.warning('K3s devbox 应用 %s 删除资源 %s 异常：%s', app_name or pod_name, resource_name, exc)

        if strict and errors:
            raise RuntimeError('删除 K3s 资源失败：' + '; '.join(errors))

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
            'ssh_username': annotations.get('campus-ai/ssh-username'),
            'webssh_url': K3SService._webssh_url_from_annotations(annotations, app_name),
            'native_ssh_command': annotations.get('campus-ai/native-ssh-command'),
            'is_published': False,
        }

    @staticmethod
    def _webssh_url_from_annotations(annotations: dict[str, str], app_name: str | None) -> str | None:
        value = annotations.get('campus-ai/webssh-url')
        if value:
            return value
        return None

    @staticmethod
    def _api_exception_class():
        from kubernetes.client.rest import ApiException

        return ApiException
