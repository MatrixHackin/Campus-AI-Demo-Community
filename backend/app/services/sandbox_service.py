from __future__ import annotations

import re
from datetime import datetime, timezone
from secrets import token_hex

from fastapi import HTTPException, status

from app.core.config import Settings
from app.schemas.sandbox import SandboxCreateRequest, SandboxResponse


class SandboxService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._mock_sandboxes: dict[str, list[SandboxResponse]] = {}

    def _get_kubernetes_sdk(self):
        try:
            from kubernetes import client, config
            from kubernetes.client.rest import ApiException
            from kubernetes.config.config_exception import ConfigException
        except ImportError as exc:
            raise HTTPException(status_code=500, detail='未安装 kubernetes Python SDK') from exc

        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config(config_file=self.settings.kubeconfig_path)

        return client, ApiException

    def _build_names(self, username: str) -> tuple[str, str]:
        safe_username = re.sub(r'[^a-z0-9-]+', '-', username.lower()).strip('-') or 'user'
        suffix = token_hex(3)
        sandbox_id = f'{safe_username}-{suffix}'
        pod_name = f'dev-sandbox-{sandbox_id}'[:63].rstrip('-')
        return sandbox_id, pod_name

    def _build_sandbox_from_pod(self, pod, username: str) -> SandboxResponse:
        return SandboxResponse(
            sandbox_id=(pod.metadata.labels or {}).get('sandbox-id', pod.metadata.name),
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            status=pod.status.phase,
            image=pod.spec.containers[0].image if pod.spec.containers else 'unknown',
            created_at=pod.metadata.creation_timestamp,
            access_hint='可在这里继续扩展访问地址、日志、端口转发等能力。',
            owner=username,
        )

    def _create_mock_sandbox(self, username: str, payload: SandboxCreateRequest) -> SandboxResponse:
        sandbox_id, pod_name = self._build_names(username)
        sandbox = SandboxResponse(
            sandbox_id=sandbox_id,
            pod_name=pod_name,
            namespace=self.settings.kubernetes_namespace,
            status='mock-created',
            image=payload.image or self.settings.default_sandbox_image,
            created_at=datetime.now(timezone.utc),
            access_hint='当前为 MOCK_KUBERNETES=true，本次仅模拟创建。接入真实集群后可返回 Pod/Service 地址。',
            owner=username,
        )
        self._mock_sandboxes.setdefault(username, []).insert(0, sandbox)
        return sandbox

    def create_sandbox(self, username: str, payload: SandboxCreateRequest) -> SandboxResponse:
        if self.settings.mock_kubernetes:
            return self._create_mock_sandbox(username, payload)

        try:
            client, ApiException = self._get_kubernetes_sdk()
            api = client.CoreV1Api()
            sandbox_id, pod_name = self._build_names(username)
            namespace = self.settings.kubernetes_namespace

            container = client.V1Container(
                name='sandbox',
                image=payload.image or self.settings.default_sandbox_image,
                command=payload.command or self.settings.default_sandbox_command,
                args=payload.args,
                env=[client.V1EnvVar(name=k, value=v) for k, v in payload.env.items()],
                resources=client.V1ResourceRequirements(
                    requests={
                        'cpu': payload.cpu_request,
                        'memory': payload.memory_request,
                    }
                ),
            )

            pod_manifest = client.V1Pod(
                metadata=client.V1ObjectMeta(
                    name=pod_name,
                    labels={
                        'app': 'campus-ai-sandbox',
                        'sandbox-owner': username,
                        'sandbox-id': sandbox_id,
                    },
                ),
                spec=client.V1PodSpec(restart_policy='Never', containers=[container]),
            )

            try:
                api.read_namespace(namespace)
            except ApiException as exc:
                if exc.status == 404:
                    namespaces = client.CoreV1Api()
                    namespaces.create_namespace(
                        client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                    )
                else:
                    raise

            api.create_namespaced_pod(namespace=namespace, body=pod_manifest)

            return SandboxResponse(
                sandbox_id=sandbox_id,
                pod_name=pod_name,
                namespace=namespace,
                status='creating',
                image=container.image,
                created_at=datetime.now(timezone.utc),
                access_hint='Pod 已提交到 Kubernetes，后续可扩展为返回 Service/Ingress/VS Code Web 地址。',
                owner=username,
            )
        except ApiException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f'Kubernetes API 调用失败: {exc.reason}',
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f'创建开发沙盒失败: {str(exc)}',
            ) from exc

    def list_sandboxes(self, username: str) -> list[SandboxResponse]:
        if self.settings.mock_kubernetes:
            return self._mock_sandboxes.get(username, [])

        try:
            client, _ = self._get_kubernetes_sdk()
            api = client.CoreV1Api()
            pods = api.list_namespaced_pod(
                namespace=self.settings.kubernetes_namespace,
                label_selector=f'app=campus-ai-sandbox,sandbox-owner={username}',
            )
            items = [self._build_sandbox_from_pod(pod, username) for pod in pods.items]
            return sorted(items, key=lambda item: item.created_at, reverse=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'获取沙盒列表失败: {str(exc)}') from exc
