from __future__ import annotations

import logging
import base64
import ipaddress
import json
import re
import shlex
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from app.core.config import Settings
from app.services.container_repository import ContainerRepository
from app.services.container_usage_service import ContainerUsageService
from app.services.harbor_service import HarborService
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
        self.container_usage_service = ContainerUsageService(settings)
        self.harbor_service = HarborService(settings)
        self.publication_repository = PublicationRepository(settings)
        self._core_v1 = None
        self._networking_v1 = None
        self._batch_v1 = None

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

    def _resolve_devbox_image(self, *, image: str | None, email: str | None) -> tuple[str, bool]:
        """解析用户从“镜像仓库”点选的镜像。

        前端“镜像仓库”始终保持一个选中项，默认是公有 devbox，因此这里不再反查 Harbor
        校验镜像是否存在，只判断是否需要为私有镜像挂载当前用户 namespace 的 pull secret。
        """
        image_ref = (image or self.settings.k3s_devbox_image).strip()
        if not image_ref:
            image_ref = self.settings.k3s_devbox_image.strip()
        if any(char.isspace() for char in image_ref):
            raise ValueError('镜像地址不合法')

        default_image = self.settings.k3s_devbox_image.strip()
        if image_ref == default_image:
            return image_ref, False

        public_prefix = (
            f'{self.settings.harbor_registry.rstrip("/")}/'
            f'{self.settings.harbor_public_project.strip().strip("/")}/'
        )
        if self.settings.harbor_public_project and image_ref.startswith(public_prefix):
            return image_ref, False

        if not email:
            raise ValueError('当前用户缺少邮箱，无法拉取私有镜像')
        return image_ref, True

    def create_devbox_container(
        self,
        emp_id: str | None,
        username: str,
        email: str | None,
        app_name: str,
        connection_password: str,
        image: str | None = None,
        needs_gpu: bool = False,
        gpu_count: int = 0,
        cpu_cores: int | None = None,
        memory_gb: int | None = None,
        shm_gb: int | None = None,
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
        image_ref, needs_private_pull_secret = self._resolve_devbox_image(image=image, email=email)
        resources = self._resolve_devbox_resources(
            needs_gpu=needs_gpu,
            gpu_count=gpu_count,
            cpu_cores=cpu_cores,
            memory_gb=memory_gb,
            shm_gb=shm_gb,
        )
        image_pull_secret_name = None
        if needs_private_pull_secret:
            image_pull_secret_name = self._ensure_harbor_pull_secret(email, namespace)
        pod_name = f'campus-devbox-{uuid.uuid4().hex[:8]}'
        ssh_service_name = f'{normalized_app_name}-ssh-svc'
        user_workspace_pvc_name = None
        if self.settings.k3s_user_workspace_enabled:
            user_workspace_pvc_name = self._ensure_user_workspace_pvc(namespace)
        pod = self._devbox_pod_body(
            pod_name=pod_name,
            namespace=namespace,
            emp_id=emp_id or '',
            app_name=normalized_app_name,
            ssh_username=username,
            image_ref=image_ref,
            image_pull_secret_name=image_pull_secret_name,
            resources=resources,
            user_workspace_pvc_name=user_workspace_pvc_name,
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
            'image': image_ref,
            'cpu': resources['cpu'],
            'memory': resources['memory'],
            'gpu_count': resources['gpu_count'],
            'shm': resources.get('shm'),
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
            pods = self._core().list_namespaced_pod(
                namespace=namespace,
                label_selector='app=campus-ai-devbox',
            ).items
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

        containers = [
            self._container_item_from_pod(pod)
            for pod in pods
            if not (pod.metadata and pod.metadata.deletion_timestamp)
        ]
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

    def _resolve_devbox_resources(
        self,
        *,
        needs_gpu: bool,
        gpu_count: int,
        cpu_cores: int | None,
        memory_gb: int | None,
        shm_gb: int | None,
    ) -> dict[str, Any]:
        if not needs_gpu:
            return {
                'cpu': self.settings.k3s_devbox_cpu,
                'memory': self.settings.k3s_devbox_memory,
                'gpu_count': 0,
                'shm': None,
            }

        if gpu_count < 1 or gpu_count > 2:
            raise ValueError('GPU 数量必须为 1 到 2 张')
        if cpu_cores is None or memory_gb is None or shm_gb is None:
            raise ValueError('申请 GPU 开发沙盒时必须填写 CPU、内存和 /dev/shm')

        max_cpu = 16 * gpu_count
        max_memory = 32 * gpu_count
        max_shm = 8 * gpu_count
        if cpu_cores < 1 or cpu_cores > max_cpu:
            raise ValueError(f'CPU 核数必须在 1 到 {max_cpu} 之间')
        if memory_gb < 1 or memory_gb > max_memory:
            raise ValueError(f'内存必须在 1GB 到 {max_memory}GB 之间')
        if shm_gb < 1 or shm_gb > max_shm:
            raise ValueError(f'/dev/shm 必须在 1GB 到 {max_shm}GB 之间')

        return {
            'cpu': str(cpu_cores),
            'memory': f'{memory_gb}Gi',
            'gpu_count': gpu_count,
            'shm': f'{shm_gb}Gi',
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
        pod = None
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

        if pod is not None:
            try:
                self.container_usage_service.collect_pod(pod=pod, final=True)
            except Exception as exc:
                logger.warning('删除容器 %s 前汇总资源消耗失败，继续删除：%s', pod_name, exc)

        self._delete_app_resources(namespace=namespace, pod_name=pod_name, app_name=app_name, strict=True)
        try:
            self.publication_repository.delete_by_pod_name(pod_name, delete_likes=True)
        except Exception as exc:
            logger.warning('删除容器 %s 时取消发布记录失败，跳过：%s', pod_name, exc)
        self.container_repository.delete_container_record(pod_name=pod_name)
        return {
            'pod_name': pod_name,
            'namespace': namespace,
            'app_name': app_name,
            'status': 'deleting',
        }

    def commit_user_container(
        self,
        emp_id: str | None,
        username: str,
        email: str | None,
        pod_name: str,
        image_name: str,
    ) -> dict[str, Any]:
        """提交一个特权 Job，将当前用户 Pod 的容器保存为 Harbor 私有镜像。"""
        if not pod_name or not K8S_DNS_LABEL_PATTERN.fullmatch(pod_name):
            raise ValueError('Pod 名称不合法')
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法保存容器')
        if not email:
            raise RuntimeError('当前用户缺少邮箱，无法保存个人镜像')
        if not self.settings.harbor_registry.strip():
            raise RuntimeError('镜像仓库暂不可用')
        if not self.settings.harbor_admin_username or not self.settings.harbor_admin_password:
            raise RuntimeError('镜像保存服务暂不可用')

        normalized_image_name = self._normalize_commit_image_name(image_name)
        namespace = self.namespace_for_emp_id(emp_id)
        record = self.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            raise FileNotFoundError('未找到容器记录')
        if record.get('username') and record['username'] != username:
            raise PermissionError('无权保存该容器')

        try:
            pod = self._core().read_namespaced_pod(name=pod_name, namespace=namespace)
        except self._api_exception_class() as exc:
            if exc.status == 404:
                raise FileNotFoundError('未找到容器 Pod') from exc
            logger.warning('K3s Pod %s/%s 查询失败：%s', namespace, pod_name, exc)
            raise RuntimeError(f'查询容器失败：{exc.reason or exc.status}') from exc

        if not pod.spec or not pod.spec.node_name:
            raise RuntimeError('容器尚未调度到节点，无法保存')
        if pod.status and pod.status.phase != 'Running':
            raise RuntimeError('只有运行中的容器可以保存')

        container_id = self._pod_container_id(pod)
        if not container_id:
            raise RuntimeError('容器尚未就绪，无法获取 containerd ID')

        try:
            self.harbor_service.ensure_user_private_project(email)
            project_name = self._harbor_user_project_name(email)
            push_registry = self._commit_push_registry()
            pull_secret_name = self._ensure_harbor_pull_secret(email, namespace)
            credentials_secret_name = self._ensure_harbor_credentials_secret(email, namespace)
        except Exception as exc:
            logger.warning('准备保存容器所需 Harbor 私有项目或 imagePullSecret 失败：%s', exc)
            raise RuntimeError(f'准备个人镜像仓库失败：{exc}') from exc

        image_ref = f'{push_registry}/{project_name}/{normalized_image_name}:latest'
        job_name = f'commit-{uuid.uuid4().hex[:8]}'
        job_namespace = namespace

        try:
            self._batch().create_namespaced_job(
                namespace=job_namespace,
                body=self._commit_job_body(
                    job_name=job_name,
                    job_namespace=job_namespace,
                    secret_name=credentials_secret_name,
                    source_namespace=namespace,
                    pod_name=pod_name,
                    node_name=pod.spec.node_name,
                    container_id=container_id,
                    push_registry=push_registry,
                    image_pull_secret_name=pull_secret_name,
                    image_ref=image_ref,
                ),
            )
        except self._api_exception_class() as exc:
            logger.warning('创建保存容器 Job %s 失败：%s', job_name, exc)
            raise RuntimeError(f'提交保存任务失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('创建保存容器 Job %s 异常：%s', job_name, exc)
            raise RuntimeError(f'提交保存任务失败：{exc}') from exc

        return {
            'job_name': job_name,
            'pod_name': pod_name,
            'namespace': namespace,
            'image': image_ref,
            'status': 'Running',
            'message': '保存任务已提交，正在生成并推送镜像',
        }

    def get_commit_job_status(self, emp_id: str | None, job_name: str) -> dict[str, Any]:
        """查询当前用户保存容器 Job 的状态。"""
        if not job_name or not K8S_DNS_LABEL_PATTERN.fullmatch(job_name):
            raise ValueError('Job 名称不合法')
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法查询保存任务')

        namespace = self.namespace_for_emp_id(emp_id)
        job_namespace = namespace
        try:
            job = self._batch().read_namespaced_job(name=job_name, namespace=job_namespace)
        except self._api_exception_class() as exc:
            if exc.status == 404:
                return {
                    'job_name': job_name,
                    'status': 'NotFound',
                    'message': '保存任务不存在或已被清理',
                    'image': None,
                }
            logger.warning('查询保存容器 Job %s 失败：%s', job_name, exc)
            raise RuntimeError(f'查询保存任务失败：{exc.reason or exc.status}') from exc

        labels = job.metadata.labels if job.metadata and job.metadata.labels else {}
        annotations = job.metadata.annotations if job.metadata and job.metadata.annotations else {}
        if labels.get('campus-ai/source-namespace') != namespace:
            raise PermissionError('无权查询该保存任务')

        status = 'Pending'
        message = '保存任务等待运行'
        if job.status:
            if job.status.succeeded:
                status = 'Succeeded'
                message = '镜像保存成功'
            elif job.status.failed:
                status = 'Failed'
                message = '镜像保存失败'
            elif job.status.active:
                status = 'Running'
                message = '正在保存镜像...'

        return {
            'job_name': job_name,
            'status': status,
            'message': message,
            'image': annotations.get('campus-ai/commit-image'),
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
            self._ensure_user_network_policies(namespace)
            return namespace
        except self._api_exception_class() as exc:
            if exc.status != 404:
                logger.warning('K3s namespace %s 查询失败：%s', namespace, exc)
                raise RuntimeError(f'查询 namespace 失败：{exc.reason or exc.status}') from exc

        try:
            core_v1.create_namespace(self._namespace_body(namespace, emp_id))
            logger.info('K3s namespace %s 创建成功', namespace)
            self._ensure_user_network_policies(namespace)
            return namespace
        except self._api_exception_class() as exc:
            if exc.status == 409:
                logger.info('K3s namespace %s 已存在', namespace)
                self._ensure_user_network_policies(namespace)
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

    def _batch(self):
        if self._batch_v1 is None:
            from kubernetes import client

            self._core()
            self._batch_v1 = client.BatchV1Api()
        return self._batch_v1

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

    def _ensure_user_network_policies(self, namespace: str) -> None:
        """为用户 namespace 下发开发沙盒网络隔离策略。

        策略目标是：默认隔离 devbox Pod，只放行不影响正常开发的必要流量：
        Traefik -> Pod:3000、DNS、公网 80/443（排除私网/metadata 网段）以及显式配置的内网白名单。
        Kubernetes NetworkPolicy 没有显式 deny 语义，因此这里使用 default-deny + allowlist 组合。
        """
        if not self.settings.k3s_network_policy_enabled:
            return

        policies = [
            self._devbox_default_deny_network_policy(namespace),
            self._devbox_allow_traefik_network_policy(namespace),
            self._devbox_allow_dns_network_policy(namespace),
        ]
        if self.settings.k3s_network_policy_public_web_egress_enabled:
            policies.append(self._devbox_allow_public_web_egress_network_policy(namespace))

        for policy in policies:
            self._apply_network_policy(namespace, policy)

        internal_policy = self._devbox_allow_internal_egress_network_policy(namespace)
        if internal_policy is not None:
            self._apply_network_policy(namespace, internal_policy)
        else:
            self._delete_network_policy_if_exists(namespace, 'campus-ai-allow-approved-internal-egress')

    def _apply_network_policy(self, namespace: str, policy) -> None:
        api_exception = self._api_exception_class()
        policy_name = policy.metadata.name
        try:
            existing = self._networking().read_namespaced_network_policy(name=policy_name, namespace=namespace)
            if existing.metadata and existing.metadata.resource_version:
                policy.metadata.resource_version = existing.metadata.resource_version
            self._networking().replace_namespaced_network_policy(
                name=policy_name,
                namespace=namespace,
                body=policy,
            )
        except api_exception as exc:
            if exc.status == 404:
                self._networking().create_namespaced_network_policy(namespace=namespace, body=policy)
                return
            logger.warning('应用 NetworkPolicy %s/%s 失败：%s', namespace, policy_name, exc)
            raise RuntimeError(f'应用网络隔离策略失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('应用 NetworkPolicy %s/%s 异常：%s', namespace, policy_name, exc)
            raise RuntimeError(f'应用网络隔离策略失败：{exc}') from exc

    def _delete_network_policy_if_exists(self, namespace: str, policy_name: str) -> None:
        api_exception = self._api_exception_class()
        try:
            self._networking().read_namespaced_network_policy(name=policy_name, namespace=namespace)
        except api_exception as exc:
            if exc.status == 404:
                return
            logger.warning('查询 NetworkPolicy %s/%s 失败：%s', namespace, policy_name, exc)
            raise RuntimeError(f'查询网络隔离策略失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('查询 NetworkPolicy %s/%s 异常：%s', namespace, policy_name, exc)
            raise RuntimeError(f'查询网络隔离策略失败：{exc}') from exc

        try:
            self._networking().delete_namespaced_network_policy(name=policy_name, namespace=namespace)
        except api_exception as exc:
            if exc.status != 404:
                logger.warning('删除 NetworkPolicy %s/%s 失败：%s', namespace, policy_name, exc)
                raise RuntimeError(f'删除网络隔离策略失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('删除 NetworkPolicy %s/%s 异常：%s', namespace, policy_name, exc)
            raise RuntimeError(f'删除网络隔离策略失败：{exc}') from exc

    @staticmethod
    def _devbox_pod_selector():
        from kubernetes import client

        return client.V1LabelSelector(match_labels={'app': 'campus-ai-devbox'})

    @staticmethod
    def _network_policy_meta(namespace: str, name: str):
        from kubernetes import client

        return client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels={
                'app.kubernetes.io/managed-by': 'campus-ai',
                'campus-ai/network-policy': 'devbox',
            },
        )

    def _devbox_default_deny_network_policy(self, namespace: str):
        from kubernetes import client

        return client.V1NetworkPolicy(
            api_version='networking.k8s.io/v1',
            kind='NetworkPolicy',
            metadata=self._network_policy_meta(namespace, 'campus-ai-devbox-default-deny'),
            spec=client.V1NetworkPolicySpec(
                pod_selector=self._devbox_pod_selector(),
                policy_types=['Ingress', 'Egress'],
                ingress=[],
                egress=[],
            ),
        )

    def _devbox_allow_traefik_network_policy(self, namespace: str):
        from kubernetes import client

        traefik_namespace = self.settings.k3s_network_policy_traefik_namespace.strip() or 'kube-system'
        traefik_labels = self._parse_label_pairs(self.settings.k3s_network_policy_traefik_pod_labels)
        return client.V1NetworkPolicy(
            api_version='networking.k8s.io/v1',
            kind='NetworkPolicy',
            metadata=self._network_policy_meta(namespace, 'campus-ai-allow-traefik-web-ingress'),
            spec=client.V1NetworkPolicySpec(
                pod_selector=self._devbox_pod_selector(),
                policy_types=['Ingress'],
                ingress=[
                    client.V1NetworkPolicyIngressRule(
                        _from=[
                            client.V1NetworkPolicyPeer(
                                namespace_selector=client.V1LabelSelector(
                                    match_labels={'kubernetes.io/metadata.name': traefik_namespace}
                                ),
                                pod_selector=client.V1LabelSelector(match_labels=traefik_labels),
                            )
                        ],
                        ports=[client.V1NetworkPolicyPort(protocol='TCP', port=3000)],
                    )
                ],
            ),
        )

    def _devbox_allow_dns_network_policy(self, namespace: str):
        from kubernetes import client

        dns_cidrs = [self._cidr_for_address(value) for value in self.settings.k3s_devbox_dns_nameservers]
        dns_cidrs = [value for value in dns_cidrs if value]
        if dns_cidrs:
            peers = [
                client.V1NetworkPolicyPeer(ip_block=client.V1IPBlock(cidr=cidr))
                for cidr in dns_cidrs
            ]
        else:
            coredns_namespace = self.settings.k3s_network_policy_coredns_namespace.strip() or 'kube-system'
            coredns_labels = self._parse_label_pairs(self.settings.k3s_network_policy_coredns_pod_labels)
            peers = [
                client.V1NetworkPolicyPeer(
                    namespace_selector=client.V1LabelSelector(
                        match_labels={'kubernetes.io/metadata.name': coredns_namespace}
                    ),
                    pod_selector=client.V1LabelSelector(match_labels=coredns_labels),
                )
            ]
        return client.V1NetworkPolicy(
            api_version='networking.k8s.io/v1',
            kind='NetworkPolicy',
            metadata=self._network_policy_meta(namespace, 'campus-ai-allow-dns-egress'),
            spec=client.V1NetworkPolicySpec(
                pod_selector=self._devbox_pod_selector(),
                policy_types=['Egress'],
                egress=[
                    client.V1NetworkPolicyEgressRule(
                        to=peers,
                        ports=[
                            client.V1NetworkPolicyPort(protocol='UDP', port=53),
                            client.V1NetworkPolicyPort(protocol='TCP', port=53),
                        ],
                    )
                ],
            ),
        )

    def _devbox_allow_public_web_egress_network_policy(self, namespace: str):
        from kubernetes import client

        except_cidrs = [
            cidr
            for cidr in (
                self._normalize_cidr(value)
                for value in self.settings.k3s_network_policy_public_web_except_cidrs
            )
            if cidr
        ]
        return client.V1NetworkPolicy(
            api_version='networking.k8s.io/v1',
            kind='NetworkPolicy',
            metadata=self._network_policy_meta(namespace, 'campus-ai-allow-public-web-egress'),
            spec=client.V1NetworkPolicySpec(
                pod_selector=self._devbox_pod_selector(),
                policy_types=['Egress'],
                egress=[
                    client.V1NetworkPolicyEgressRule(
                        to=[
                            client.V1NetworkPolicyPeer(
                                ip_block=client.V1IPBlock(cidr='0.0.0.0/0', _except=except_cidrs or None)
                            )
                        ],
                        ports=[
                            client.V1NetworkPolicyPort(protocol='TCP', port=80),
                            client.V1NetworkPolicyPort(protocol='TCP', port=443),
                        ],
                    )
                ],
            ),
        )

    def _devbox_allow_internal_egress_network_policy(self, namespace: str):
        from kubernetes import client

        egress_rules = []
        for raw_rule in self.settings.k3s_network_policy_internal_allow_rules:
            parsed = self._parse_internal_allow_rule(raw_rule)
            if parsed is None:
                continue
            cidr, port, protocol = parsed
            egress_rules.append(
                client.V1NetworkPolicyEgressRule(
                    to=[client.V1NetworkPolicyPeer(ip_block=client.V1IPBlock(cidr=cidr))],
                    ports=[client.V1NetworkPolicyPort(protocol=protocol, port=port)],
                )
            )
        if not egress_rules:
            return None
        return client.V1NetworkPolicy(
            api_version='networking.k8s.io/v1',
            kind='NetworkPolicy',
            metadata=self._network_policy_meta(namespace, 'campus-ai-allow-approved-internal-egress'),
            spec=client.V1NetworkPolicySpec(
                pod_selector=self._devbox_pod_selector(),
                policy_types=['Egress'],
                egress=egress_rules,
            ),
        )

    @staticmethod
    def _parse_label_pairs(values: list[str]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for value in values:
            if '=' not in value:
                raise RuntimeError(f'Traefik Pod 标签配置不合法：{value}')
            key, label_value = value.split('=', 1)
            key = key.strip()
            label_value = label_value.strip()
            if not key or not label_value:
                raise RuntimeError(f'Traefik Pod 标签配置不合法：{value}')
            labels[key] = label_value
        if not labels:
            raise RuntimeError('Traefik Pod 标签配置不能为空')
        return labels

    @staticmethod
    def _cidr_for_address(value: str) -> str | None:
        normalized = K3SService._normalize_cidr(value)
        if normalized:
            return normalized
        stripped = value.strip()
        if not stripped:
            return None
        try:
            address = ipaddress.ip_address(stripped)
        except ValueError as exc:
            raise RuntimeError(f'NetworkPolicy IP 地址不合法：{value}') from exc
        return f'{address}/32' if address.version == 4 else f'{address}/128'

    @staticmethod
    def _normalize_cidr(value: str) -> str | None:
        stripped = value.strip()
        if not stripped:
            return None
        if '/' not in stripped:
            return None
        try:
            return str(ipaddress.ip_network(stripped, strict=False))
        except ValueError as exc:
            raise RuntimeError(f'NetworkPolicy CIDR 不合法：{value}') from exc

    @staticmethod
    def _parse_internal_allow_rule(raw_rule: str) -> tuple[str, int, str] | None:
        """解析 K3S_NETWORK_POLICY_INTERNAL_ALLOW_RULES。

        格式：CIDR:PORT[/PROTOCOL]，例如：
        - 10.120.17.137/32:5053/tcp
        - 10.120.20.10/32:443
        """
        value = raw_rule.strip()
        if not value:
            return None
        cidr_part, sep, port_part = value.rpartition(':')
        if not sep or not cidr_part or not port_part:
            raise RuntimeError(f'内网白名单规则不合法：{raw_rule}')
        if '/' in port_part:
            port_text, protocol = port_part.split('/', 1)
        else:
            port_text, protocol = port_part, 'TCP'
        protocol = protocol.strip().upper()
        if protocol not in {'TCP', 'UDP', 'SCTP'}:
            raise RuntimeError(f'内网白名单协议不合法：{raw_rule}')
        try:
            port = int(port_text.strip())
        except ValueError as exc:
            raise RuntimeError(f'内网白名单端口不合法：{raw_rule}') from exc
        if port < 1 or port > 65535:
            raise RuntimeError(f'内网白名单端口不合法：{raw_rule}')
        cidr = K3SService._normalize_cidr(cidr_part)
        if not cidr:
            raise RuntimeError(f'内网白名单 CIDR 不合法：{raw_rule}')
        return cidr, port, protocol

    def _devbox_pod_body(
        self,
        pod_name: str,
        namespace: str,
        emp_id: str,
        app_name: str,
        ssh_username: str,
        image_ref: str,
        image_pull_secret_name: str | None = None,
        resources: dict[str, Any] | None = None,
        user_workspace_pvc_name: str | None = None,
    ):
        from kubernetes import client

        resolved_resources = resources or {
            'cpu': self.settings.k3s_devbox_cpu,
            'memory': self.settings.k3s_devbox_memory,
            'gpu_count': 0,
            'shm': None,
        }
        resource_value = {
            'cpu': resolved_resources['cpu'],
            'memory': resolved_resources['memory'],
        }
        gpu_count = int(resolved_resources.get('gpu_count') or 0)
        if gpu_count > 0:
            resource_value['nvidia.com/gpu'] = str(gpu_count)

        shm_size = resolved_resources.get('shm')
        volume_mounts = []
        volumes = []
        if shm_size:
            volume_mounts.append(client.V1VolumeMount(name='dev-shm', mount_path='/dev/shm'))
            volumes.append(
                client.V1Volume(
                    name='dev-shm',
                    empty_dir=client.V1EmptyDirVolumeSource(
                        medium='Memory',
                        size_limit=shm_size,
                    ),
                )
            )
        if user_workspace_pvc_name:
            volume_mounts.append(
                client.V1VolumeMount(
                    name='user-workspace',
                    mount_path=self._user_workspace_mount_path(ssh_username),
                )
            )
            volumes.append(
                client.V1Volume(
                    name='user-workspace',
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=user_workspace_pvc_name,
                    ),
                )
            )
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
                    'campus-ai/image': image_ref,
                },
            ),
            spec=client.V1PodSpec(
                restart_policy='Never',
                node_selector={'competition': 'true'},
                affinity=self._devbox_affinity(needs_gpu=gpu_count > 0),
                dns_policy='None' if self.settings.k3s_devbox_dns_nameservers else 'ClusterFirst',
                dns_config=self._devbox_dns_config(),
                image_pull_secrets=[
                    client.V1LocalObjectReference(name=image_pull_secret_name)
                ] if image_pull_secret_name else None,
                containers=[
                    client.V1Container(
                        name='devbox',
                        image=image_ref,
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
                        volume_mounts=volume_mounts or None,
                    )
                ],
                volumes=volumes or None,
            ),
        )

    def _ensure_user_workspace_pvc(self, namespace: str) -> str:
        """确保用户 namespace 下存在一个用户级 Longhorn RWX 工作区 PVC。"""
        pvc_name = self.settings.k3s_user_workspace_pvc_name.strip() or 'user-workspace'
        if not K8S_DNS_LABEL_PATTERN.fullmatch(pvc_name):
            raise RuntimeError(f'用户持久存储 PVC 名称不合法：{pvc_name}')

        api_exception = self._api_exception_class()
        try:
            self._core().read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
            return pvc_name
        except api_exception as exc:
            if exc.status != 404:
                logger.warning('查询用户持久存储 PVC %s/%s 失败：%s', namespace, pvc_name, exc)
                raise RuntimeError(f'查询用户持久存储失败：{exc.reason or exc.status}') from exc

        try:
            self._core().create_namespaced_persistent_volume_claim(
                namespace=namespace,
                body=self._user_workspace_pvc_body(pvc_name),
            )
            logger.info('用户持久存储 PVC %s/%s 创建成功', namespace, pvc_name)
            return pvc_name
        except api_exception as exc:
            if exc.status == 409:
                return pvc_name
            logger.warning('创建用户持久存储 PVC %s/%s 失败：%s', namespace, pvc_name, exc)
            raise RuntimeError(f'创建用户持久存储失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('创建用户持久存储 PVC %s/%s 异常：%s', namespace, pvc_name, exc)
            raise RuntimeError(f'创建用户持久存储失败：{exc}') from exc

    def _user_workspace_pvc_body(self, pvc_name: str):
        from kubernetes import client

        return client.V1PersistentVolumeClaim(
            api_version='v1',
            kind='PersistentVolumeClaim',
            metadata=client.V1ObjectMeta(
                name=pvc_name,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/user-workspace': 'true',
                },
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=[self.settings.k3s_user_workspace_access_mode],
                storage_class_name=self.settings.k3s_user_workspace_storage_class,
                resources=client.V1VolumeResourceRequirements(
                    requests={
                        'storage': self.settings.k3s_user_workspace_size,
                    },
                ),
            ),
        )

    def _user_workspace_mount_path(self, ssh_username: str) -> str:
        del ssh_username
        mount_path = self.settings.k3s_user_workspace_mount_path.strip() or '/mydata'
        if not mount_path.startswith('/') or mount_path == '/':
            raise RuntimeError(f'用户持久存储挂载路径不合法：{mount_path}')
        if '"' in mount_path or '$' in mount_path or '`' in mount_path:
            raise RuntimeError(f'用户持久存储挂载路径不合法：{mount_path}')
        return mount_path

    @staticmethod
    def _devbox_affinity(*, needs_gpu: bool):
        from kubernetes import client

        if needs_gpu:
            return client.V1Affinity(
                node_affinity=client.V1NodeAffinity(
                    required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                        node_selector_terms=[
                            client.V1NodeSelectorTerm(
                                match_expressions=[
                                    client.V1NodeSelectorRequirement(
                                        key='nvidia.com/gpu.present',
                                        operator='Exists',
                                    )
                                ]
                            )
                        ]
                    )
                )
            )

        return client.V1Affinity(
            node_affinity=client.V1NodeAffinity(
                preferred_during_scheduling_ignored_during_execution=[
                    client.V1PreferredSchedulingTerm(
                        weight=100,
                        preference=client.V1NodeSelectorTerm(
                            match_expressions=[
                                client.V1NodeSelectorRequirement(
                                    key='nvidia.com/gpu.present',
                                    operator='DoesNotExist',
                                )
                            ]
                        ),
                    ),
                ]
            )
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
            f'mkdir -p {shlex.quote(self._user_workspace_mount_path(""))}; '
            f'chown "$USERNAME:$USERNAME" {shlex.quote(self._user_workspace_mount_path(""))} 2>/dev/null || true; '
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

    @staticmethod
    def _normalize_commit_image_name(image_name: str) -> str:
        normalized = image_name.strip().lower()
        if len(normalized) > 80:
            raise ValueError('镜像名称最多 80 个字符')
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', normalized):
            raise ValueError('镜像名称只能包含小写字母、数字、点、下划线和中划线，且必须以字母或数字开头')
        return normalized

    def _harbor_user_project_name(self, email: str) -> str:
        safe_email = email.strip().lower().replace('@', '-at-').replace('.', '-dot-')
        return f'{safe_email}{self.settings.harbor_user_project_suffix}'

    def _commit_push_registry(self) -> str:
        """保存容器时 nerdctl 实际登录/推送的 registry host。

        HARBOR_REGISTRY 用于工作台展示和业务镜像名，通常是 gpunion2.io；
        但 commit Job 运行在集群内，不能依赖 gpunion2.io 的 DNS/HTTPS。
        因此默认从 HARBOR_URL 提取真实 HTTP Harbor 入口，如 10.120.17.137:5053。
        """
        configured = self.settings.k3s_commit_push_registry.strip()
        if configured:
            parsed = urlparse(configured)
            registry = parsed.netloc or parsed.path
            registry = registry.strip().strip('/')
            if registry:
                return registry

        harbor_url = self.settings.harbor_url.strip()
        if harbor_url:
            parsed = urlparse(harbor_url)
            if parsed.netloc:
                return parsed.netloc

        return self.settings.harbor_registry.rstrip('/')

    def _harbor_pull_secret_name(self, email: str) -> str:
        safe_email = email.strip().lower().replace('@', '-at-').replace('.', '-dot-')
        secret_name = f'{safe_email}-harbor'
        secret_name = re.sub(r'[^a-z0-9.-]+', '-', secret_name).strip('-')
        return secret_name[:253].rstrip('-') or 'harbor-pull-secret'

    def _harbor_credentials_secret_name(self, email: str) -> str:
        safe_email = email.strip().lower().replace('@', '-at-').replace('.', '-dot-')
        secret_name = f'{safe_email}-harbor-credentials'
        secret_name = re.sub(r'[^a-z0-9.-]+', '-', secret_name).strip('-')
        return secret_name[:253].rstrip('-') or 'harbor-credentials'

    def _ensure_harbor_pull_secret(self, email: str | None, namespace: str) -> str | None:
        if not email:
            return None
        if not self.harbor_service.configured:
            logger.warning('Harbor 未配置，跳过创建 namespace %s 的 imagePullSecret', namespace)
            return None

        normalized_email = email.strip().lower()
        self.harbor_service.ensure_user_private_project(normalized_email)
        secret_name = self._harbor_pull_secret_name(normalized_email)
        secret_body = self._harbor_pull_secret_body(secret_name, normalized_email)
        try:
            self._core().create_namespaced_secret(namespace=namespace, body=secret_body)
        except self._api_exception_class() as exc:
            if exc.status == 409:
                self._core().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret_body)
            else:
                raise
        return secret_name

    def _harbor_pull_secret_body(self, secret_name: str, email: str):
        from kubernetes import client

        auths = {}
        for registry in {self.settings.harbor_registry.rstrip('/'), self._commit_push_registry()}:
            if not registry:
                continue
            auths[registry] = {
                'username': email,
                'password': self.settings.harbor_user_default_password,
                'auth': base64.b64encode(
                    f'{email}:{self.settings.harbor_user_default_password}'.encode()
                ).decode(),
            }
        docker_config = base64.b64encode(json.dumps({'auths': auths}).encode()).decode()
        return client.V1Secret(
            api_version='v1',
            kind='Secret',
            metadata=client.V1ObjectMeta(
                name=secret_name,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/harbor-pull-secret': 'true',
                },
            ),
            type='kubernetes.io/dockerconfigjson',
            data={
                '.dockerconfigjson': docker_config,
            },
        )

    def _ensure_harbor_credentials_secret(self, email: str | None, namespace: str) -> str:
        if not email:
            raise RuntimeError('当前用户缺少邮箱，无法创建 Harbor 凭据 Secret')

        normalized_email = email.strip().lower()
        secret_name = self._harbor_credentials_secret_name(normalized_email)
        secret_body = self._harbor_credentials_secret_body(secret_name, normalized_email)
        try:
            self._core().create_namespaced_secret(namespace=namespace, body=secret_body)
        except self._api_exception_class() as exc:
            if exc.status == 409:
                self._core().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret_body)
            else:
                raise
        return secret_name

    def _harbor_credentials_secret_body(self, secret_name: str, email: str):
        from kubernetes import client

        return client.V1Secret(
            api_version='v1',
            kind='Secret',
            metadata=client.V1ObjectMeta(
                name=secret_name,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/harbor-credentials-secret': 'true',
                },
            ),
            string_data={
                'username': email,
                'password': self.settings.harbor_user_default_password,
            },
            type='Opaque',
        )

    @staticmethod
    def _pod_container_id(pod) -> str | None:
        container_statuses = pod.status.container_statuses if pod.status and pod.status.container_statuses else []
        if not container_statuses:
            return None
        container_id = container_statuses[0].container_id
        if not container_id:
            return None
        return container_id.replace('containerd://', '')

    def _commit_job_body(
        self,
        *,
        job_name: str,
        job_namespace: str,
        secret_name: str,
        source_namespace: str,
        pod_name: str,
        node_name: str,
        container_id: str,
        push_registry: str,
        image_pull_secret_name: str | None,
        image_ref: str,
    ):
        from kubernetes import client

        socket_mount_path = self.settings.k3s_commit_containerd_socket
        nerdctl_cmd = f'nerdctl --address {shlex.quote(socket_mount_path)} --namespace k8s.io'
        insecure_flag = ' --insecure-registry' if self.settings.k3s_commit_insecure_registry else ''
        command = (
            'set -eu; '
            f'printf "%s\\n" "$HARBOR_PASSWORD" | {nerdctl_cmd} login '
            f'-u "$HARBOR_USERNAME" --password-stdin {shlex.quote(push_registry)}{insecure_flag}; '
            f'{nerdctl_cmd} commit{insecure_flag} {shlex.quote(container_id)} {shlex.quote(image_ref)}; '
            f'{nerdctl_cmd} push {shlex.quote(image_ref)}{insecure_flag}'
        )
        labels = {
            'app.kubernetes.io/managed-by': 'campus-ai',
            'campus-ai/commit-job': 'true',
            'campus-ai/source-namespace': source_namespace,
            'campus-ai/source-pod': pod_name,
        }
        annotations = {
            'campus-ai/commit-image': image_ref,
        }

        return client.V1Job(
            api_version='batch/v1',
            kind='Job',
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=job_namespace,
                labels=labels,
                annotations=annotations,
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=300,
                backoff_limit=0,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels, annotations=annotations),
                    spec=client.V1PodSpec(
                        node_name=node_name,
                        restart_policy='Never',
                        image_pull_secrets=[
                            client.V1LocalObjectReference(name=image_pull_secret_name)
                        ] if image_pull_secret_name else None,
                        containers=[
                            client.V1Container(
                                name='commit-runner',
                                image=self.settings.k3s_commit_nerdctl_image,
                                security_context=client.V1SecurityContext(privileged=True),
                                command=['/bin/sh', '-c', command],
                                env=[
                                    client.V1EnvVar(
                                        name='HARBOR_USERNAME',
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name=secret_name,
                                                key='username',
                                            )
                                        ),
                                    ),
                                    client.V1EnvVar(
                                        name='HARBOR_PASSWORD',
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name=secret_name,
                                                key='password',
                                            )
                                        ),
                                    ),
                                ],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name='containerd-sock',
                                        mount_path=socket_mount_path,
                                    )
                                ],
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name='containerd-sock',
                                host_path=client.V1HostPathVolumeSource(
                                    path=self.settings.k3s_commit_host_containerd_socket,
                                    type='Socket',
                                ),
                            )
                        ],
                    ),
                ),
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
            raise RuntimeError('删除容器资源失败：' + '; '.join(errors))

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
        start_time = pod.status.start_time if pod.status and pod.status.start_time else None
        if start_time and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        return {
            'name': pod.metadata.name if pod.metadata else '',
            'image': image,
            'status': status,
            'node_name': pod.spec.node_name if pod.spec else None,
            'start_time': start_time.isoformat() if start_time else None,
            'duration': int((now - start_time).total_seconds()) if start_time else 0,
            'app_name': app_name,
            'url': annotations.get('campus-ai/public-url'),
            'ssh_username': annotations.get('campus-ai/ssh-username'),
            'webssh_url': K3SService._webssh_url_from_annotations(annotations),
            'native_ssh_command': annotations.get('campus-ai/native-ssh-command'),
            'is_published': False,
        }

    @staticmethod
    def _webssh_url_from_annotations(annotations: dict[str, str]) -> str | None:
        value = annotations.get('campus-ai/webssh-url')
        if value:
            return value
        return None

    @staticmethod
    def _api_exception_class():
        from kubernetes.client.rest import ApiException

        return ApiException
