from __future__ import annotations

import base64
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

from app.core.config import Settings, get_settings


class PodCreationError(RuntimeError):
    """Raised when a user-facing Pod creation failure reason is known."""


def _safe_k8s_name(value: str, fallback: str = 'user') -> str:
    safe = re.sub(r'[^a-z0-9-]+', '-', value.lower()).strip('-')
    return (safe or fallback)[:63].rstrip('-') or fallback


class K3SAPI:
    """当前项目使用的精简 K3s API 封装。

    与 GPUnion2-server 相比，这里只负责用户申请 Pod 需要的能力：
    - Namespace 创建/复用
    - Harbor imagePullSecret 创建/更新
    - Pod 创建、查询、删除
    - 可选 NodePort Service 创建、删除

    已删除节点管理、指定节点调度、PV/PVC/存储配额等 API 层逻辑。Pod 不设置
    spec.nodeName，由 K3s scheduler 自行调度到合适节点。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._load_kubernetes_config()
        self.v1 = client.CoreV1Api()

    def _load_kubernetes_config(self) -> None:
        try:
            config.load_incluster_config()
            return
        except ConfigException:
            pass

        kubeconfig = self.settings.kubeconfig_path or self.settings.k3s_config_path or None
        config.load_kube_config(config_file=kubeconfig)

    def namespace_for_user(self, owner: str) -> str:
        if self.settings.sandbox_namespace_mode == 'user':
            return _safe_k8s_name(owner)
        return self.settings.kubernetes_namespace

    def ensure_namespace(self, namespace: str) -> None:
        namespace = _safe_k8s_name(namespace, fallback='campus-sandbox')
        try:
            self.v1.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            )
            print(f'Namespace {namespace} 创建成功')
        except ApiException as exc:
            if exc.status == 409:
                return
            print(f'创建 Namespace {namespace} 失败: {exc}')
            raise

    def create_image_pull_secret_with_useremail(self, useremail: str, namespace: str = 'default') -> str | None:
        """为指定用户在 namespace 中创建/更新 Harbor 镜像拉取密钥。"""
        registry = self.settings.harbor_registry
        password = self.settings.harbor_user_default_password
        if not registry or not password:
            print('Harbor registry/password 未配置，跳过 imagePullSecret 创建')
            return None

        secret_name = f'{_safe_k8s_name(useremail)}-harbor'
        docker_config = {
            'auths': {
                registry: {
                    'username': useremail,
                    'password': password,
                    'auth': base64.b64encode(f'{useremail}:{password}'.encode()).decode(),
                }
            }
        }
        docker_config_json = base64.b64encode(json.dumps(docker_config).encode()).decode()
        secret = client.V1Secret(
            api_version='v1',
            kind='Secret',
            metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
            type='kubernetes.io/dockerconfigjson',
            data={'.dockerconfigjson': docker_config_json},
        )

        try:
            self.v1.create_namespaced_secret(namespace=namespace, body=secret)
            return secret_name
        except ApiException as exc:
            if exc.status != 409:
                print(f'创建 Harbor Secret 失败: {exc}')
                return None
            try:
                self.v1.replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
                return secret_name
            except ApiException as update_error:
                print(f'更新 Harbor Secret 失败: {update_error}')
                return None
        except Exception as exc:
            print(f'创建 Harbor Secret 时发生未知错误: {exc}')
            return None

    def _build_resources(
        self,
        image: str,
        gpu_count: int,
        cpu_request: str | None,
        memory_request: str | None,
    ) -> tuple[client.V1ResourceRequirements, str]:
        gpu_count = max(0, int(gpu_count or 0))
        if gpu_count > 0:
            cpu_value = str(gpu_count * self.settings.gpu_cpu_per_card)
            memory_value = f'{gpu_count * self.settings.gpu_memory_per_card_gi}Gi'
            shm_size = f'{gpu_count * self.settings.gpu_shm_per_card_gi}Gi'
            gpu_resource = 'huawei.com/Ascend910' if image == self.settings.ascend_image_name else 'nvidia.com/gpu'
            limits = {
                gpu_resource: str(gpu_count),
                'cpu': cpu_request or cpu_value,
                'memory': memory_request or memory_value,
            }
            requests = dict(limits)
            return client.V1ResourceRequirements(limits=limits, requests=requests), shm_size

        cpu_value = cpu_request or self.settings.default_sandbox_cpu
        memory_value = memory_request or self.settings.default_sandbox_memory
        return (
            client.V1ResourceRequirements(
                limits={'cpu': cpu_value, 'memory': memory_value},
                requests={'cpu': cpu_value, 'memory': memory_value},
            ),
            self.settings.default_sandbox_shm_size,
        )

    def _wait_for_phase(self, pod_name: str, namespace: str, timeout_seconds: int) -> str:
        deadline = time.time() + timeout_seconds
        last_phase = 'Unknown'
        while time.time() < deadline:
            pod_status = self.v1.read_namespaced_pod_status(pod_name, namespace)
            last_phase = pod_status.status.phase or 'Unknown'
            if last_phase in {'Running', 'Succeeded'}:
                return last_phase
            if last_phase in {'Failed', 'Unknown'}:
                raise PodCreationError(f'Pod 状态异常: {last_phase}')
            time.sleep(2)
        return last_phase

    def create_pod(
        self,
        *,
        owner: str,
        user_email: str,
        image: str,
        namespace: str | None = None,
        sandbox_id: str | None = None,
        pod_name: str | None = None,
        gpu_count: int = 0,
        username: str | None = None,
        password: str | None = None,
        command: list[str] | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cpu_request: str | None = None,
        memory_request: str | None = None,
        pod_label: str | None = None,
        enable_nodeport: bool | None = None,
        wait_until_running: bool | None = None,
    ) -> dict[str, Any]:
        namespace = namespace or self.namespace_for_user(owner)
        self.ensure_namespace(namespace)

        image = image or self.settings.default_sandbox_image
        sandbox_id = sandbox_id or uuid.uuid4().hex[:12]
        pod_name = pod_name or f'campus-ai-{uuid.uuid4().hex[:8]}'
        container_username = username or self.settings.default_sandbox_username
        container_password = password or self.settings.default_sandbox_password
        enable_nodeport = self.settings.enable_sandbox_nodeport if enable_nodeport is None else enable_nodeport
        wait_until_running = self.settings.sandbox_wait_until_running if wait_until_running is None else wait_until_running

        secret_name = self.create_image_pull_secret_with_useremail(user_email, namespace)
        resources, shm_size = self._build_resources(image, gpu_count, cpu_request, memory_request)

        env_vars = [
            client.V1EnvVar(name='USERNAME', value=container_username),
            client.V1EnvVar(name='PASSWORD', value=container_password),
        ]
        for key, value in (env or {}).items():
            env_vars.append(client.V1EnvVar(name=key, value=value))

        container = client.V1Container(
            name='sandbox',
            image=image,
            command=command if command is not None else self.settings.default_sandbox_command,
            args=args,
            env=env_vars,
            resources=resources,
            volume_mounts=[client.V1VolumeMount(name='dshm', mount_path='/dev/shm')],
        )

        owner_label = _safe_k8s_name(owner)
        labels = {
            'app': 'campus-ai-sandbox',
            'sandbox-pod': pod_name,
            'sandbox-owner': owner_label,
            'sandbox-id': sandbox_id,
        }
        if pod_label:
            labels['label'] = _safe_k8s_name(pod_label, fallback='label')

        spec_kwargs: dict[str, Any] = {
            'restart_policy': 'Never',
            'containers': [container],
            'volumes': [
                client.V1Volume(
                    name='dshm',
                    empty_dir=client.V1EmptyDirVolumeSource(medium='Memory', size_limit=shm_size),
                )
            ],
        }
        if secret_name:
            spec_kwargs['image_pull_secrets'] = [client.V1LocalObjectReference(name=secret_name)]
        if gpu_count > 0 and image != self.settings.ascend_image_name and self.settings.nvidia_runtime_class_name:
            spec_kwargs['runtime_class_name'] = self.settings.nvidia_runtime_class_name

        pod = client.V1Pod(
            api_version='v1',
            kind='Pod',
            metadata=client.V1ObjectMeta(name=pod_name, namespace=namespace, labels=labels),
            spec=client.V1PodSpec(**spec_kwargs),
        )

        created_service = None
        try:
            self.v1.create_namespaced_pod(namespace=namespace, body=pod)
            phase = 'creating'
            if wait_until_running:
                phase = self._wait_for_phase(pod_name, namespace, self.settings.sandbox_wait_timeout_seconds)

            service_info = None
            if enable_nodeport:
                created_service = self.create_nodeport_service(
                    namespace=namespace,
                    pod_name=pod_name,
                    name=f'{pod_name}-ssh-svc',
                    port_name='ssh',
                    port=self.settings.sandbox_ssh_port,
                    target_port=self.settings.sandbox_ssh_port,
                )
                service_info = created_service

            return {
                'sandbox_id': sandbox_id,
                'pod_name': pod_name,
                'namespace': namespace,
                'status': phase,
                'image': image,
                'service': service_info,
                'created_at': datetime.now(timezone.utc),
            }
        except Exception as exc:
            print(f'创建 Pod/Service 失败: {exc}')
            try:
                self.v1.delete_namespaced_pod(pod_name, namespace, grace_period_seconds=0)
            except Exception:
                pass
            if created_service:
                self._delete_services_for_pod(namespace, pod_name)
            raise PodCreationError(f'创建 Pod/Service 失败：{exc}') from exc

    def create_nodeport_service(
        self,
        *,
        namespace: str,
        pod_name: str,
        name: str,
        port_name: str,
        port: int,
        target_port: int,
    ) -> dict[str, Any]:
        svc_body = client.V1Service(
            api_version='v1',
            kind='Service',
            metadata=client.V1ObjectMeta(name=name, labels={'sandbox-pod': pod_name}),
            spec=client.V1ServiceSpec(
                type='NodePort',
                selector={'sandbox-pod': pod_name},
                ports=[
                    client.V1ServicePort(
                        name=port_name,
                        protocol='TCP',
                        port=port,
                        target_port=target_port,
                    )
                ],
            ),
        )
        svc = self.v1.create_namespaced_service(namespace=namespace, body=svc_body)
        return {
            'name': svc.metadata.name,
            'type': svc.spec.type,
            'port': svc.spec.ports[0].port,
            'target_port': svc.spec.ports[0].target_port,
            'node_port': svc.spec.ports[0].node_port,
        }

    def create_nodeport_services(self, namespace: str, pod_name: str, service_defs: list[dict[str, Any]]) -> dict[str, int] | None:
        created_services: list[str] = []
        port_info: dict[str, int] = {}
        try:
            for service_def in service_defs:
                suffix = service_def['suffix']
                service_name = f'{pod_name}-{suffix}-svc'
                target_port = int(service_def['target_port'])
                info = self.create_nodeport_service(
                    namespace=str(namespace),
                    pod_name=pod_name,
                    name=service_name,
                    port_name=service_def.get('port_name', suffix),
                    port=target_port,
                    target_port=target_port,
                )
                created_services.append(service_name)
                port_info[f'{suffix}_port'] = info['node_port']
            return port_info
        except Exception as exc:
            print(f'创建额外 NodePort Service 失败: {exc}')
            for service_name in created_services:
                try:
                    self.v1.delete_namespaced_service(service_name, str(namespace))
                except Exception as delete_error:
                    print(f'回滚删除 Service {service_name} 失败: {delete_error}')
            return None

    def _delete_services_for_pod(self, namespace: str, pod_name: str) -> None:
        try:
            services = self.v1.list_namespaced_service(
                namespace=str(namespace),
                label_selector=f'sandbox-pod={pod_name}',
            )
            for svc in services.items:
                try:
                    self.v1.delete_namespaced_service(svc.metadata.name, str(namespace))
                except Exception as exc:
                    print(f'删除 Service {svc.metadata.name} 失败: {exc}')
        except Exception as exc:
            print(f'列举 Service 失败: {exc}')

    def delete_pod_with_svc(self, pod_name: str, namespace: str) -> dict[str, Any] | None:
        namespace = str(namespace)
        result_info: dict[str, Any] = {'pod_name': pod_name, 'namespace': namespace}
        delete_success = False

        try:
            pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            container = pod.spec.containers[0] if pod.spec.containers else None
            result_info.update(
                {
                    'image_name': container.image if container else None,
                    'status': pod.status.phase,
                    'start_time': pod.status.start_time.isoformat() if pod.status.start_time else None,
                    'sandbox_id': (pod.metadata.labels or {}).get('sandbox-id'),
                    'owner': (pod.metadata.labels or {}).get('sandbox-owner'),
                }
            )
        except ApiException as exc:
            if exc.status != 404:
                print(f'获取 Pod 信息失败: {exc}')
        except Exception as exc:
            print(f'处理 Pod 信息失败: {exc}')

        try:
            self.v1.delete_namespaced_pod(pod_name, namespace, grace_period_seconds=0)
            delete_success = True
        except ApiException as exc:
            if exc.status == 404:
                delete_success = True
            else:
                print(f'删除 Pod 失败: {exc}')
        except Exception as exc:
            print(f'删除 Pod 时发生错误: {exc}')

        self._delete_services_for_pod(namespace, pod_name)
        return result_info if delete_success else None

    def get_user_pods(self, owner: str, namespace: str | None = None, label_selector: str | None = None) -> list[dict[str, Any]]:
        namespace = namespace or self.namespace_for_user(owner)
        selectors = [f'app=campus-ai-sandbox', f'sandbox-owner={_safe_k8s_name(owner)}']
        if label_selector:
            selectors.append(label_selector)
        selector = ','.join(selectors)

        try:
            pods = self.v1.list_namespaced_pod(namespace=namespace, label_selector=selector)
            pod_list: list[dict[str, Any]] = []
            for pod in pods.items:
                container = pod.spec.containers[0] if pod.spec.containers else None
                pod_info: dict[str, Any] = {
                    'sandbox_id': (pod.metadata.labels or {}).get('sandbox-id', pod.metadata.name),
                    'pod_name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'image_name': container.image if container else 'unknown',
                    'status': pod.status.phase,
                    'created_at': pod.metadata.creation_timestamp.isoformat()
                    if pod.metadata.creation_timestamp
                    else None,
                    'start_time': pod.status.start_time.isoformat() if pod.status.start_time else None,
                    'label': (pod.metadata.labels or {}).get('label'),
                }
                try:
                    services = self.v1.list_namespaced_service(
                        namespace=namespace,
                        label_selector=f'sandbox-pod={pod.metadata.name}',
                    )
                    pod_info['services'] = [
                        {
                            'name': svc.metadata.name,
                            'type': svc.spec.type,
                            'ports': [
                                {
                                    'name': port.name,
                                    'port': port.port,
                                    'target_port': port.target_port,
                                    'node_port': port.node_port,
                                }
                                for port in (svc.spec.ports or [])
                            ],
                        }
                        for svc in services.items
                    ]
                except ApiException as exc:
                    if exc.status != 404:
                        print(f'获取 Service 信息失败: {exc}')
                pod_list.append(pod_info)
            return pod_list
        except ApiException as exc:
            if exc.status == 404:
                return []
            print(f'获取 Pods 失败: {exc}')
            raise
