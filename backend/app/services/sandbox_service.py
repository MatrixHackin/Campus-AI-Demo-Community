from __future__ import annotations

import re
from datetime import datetime, timezone
from secrets import token_hex
from typing import Any

from fastapi import HTTPException, status

from app.api.k3sapi import K3SAPI, PodCreationError
from app.core.config import Settings
from app.schemas.sandbox import SandboxCreateRequest, SandboxResponse


class SandboxService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._k3s_api: K3SAPI | None = None

    def _get_k3s_api(self) -> K3SAPI:
        if self._k3s_api is None:
            try:
                self._k3s_api = K3SAPI(settings=self.settings)
            except ImportError as exc:
                raise HTTPException(status_code=500, detail='未安装 kubernetes Python SDK') from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f'初始化 K3s 客户端失败: {str(exc)}') from exc
        return self._k3s_api

    def _namespace_for_user(self, username: str) -> str:
        if self.settings.sandbox_namespace_mode == 'user':
            return self._safe_name(username, fallback='user')
        return self.settings.kubernetes_namespace

    @staticmethod
    def _safe_name(value: str, fallback: str = 'user') -> str:
        safe = re.sub(r'[^a-z0-9-]+', '-', value.lower()).strip('-')
        return (safe or fallback)[:63].rstrip('-') or fallback

    def _build_names(self, username: str) -> tuple[str, str]:
        safe_username = self._safe_name(username)
        suffix = token_hex(3)
        sandbox_id = f'{safe_username}-{suffix}'
        pod_name = f'dev-sandbox-{sandbox_id}'[:63].rstrip('-')
        return sandbox_id, pod_name

    def _build_access_hint(self, services: list[dict[str, Any]] | None = None) -> str:
        if not services:
            return 'Pod 已提交到 K3s，由调度器自动选择节点；未创建 NodePort Service。'

        node_ports: list[str] = []
        for service in services:
            for port in service.get('ports', []) if 'ports' in service else [service]:
                node_port = port.get('node_port')
                name = port.get('name') or service.get('name') or 'service'
                if node_port:
                    node_ports.append(f'{name}: NodePort {node_port}')
        if node_ports:
            return 'Pod 已提交到 K3s，由调度器自动选择节点；Service 已创建：' + '，'.join(node_ports)
        return 'Pod 已提交到 K3s，由调度器自动选择节点；Service 已创建。'

    def create_sandbox(self, username: str, payload: SandboxCreateRequest) -> SandboxResponse:
        sandbox_id, pod_name = self._build_names(username)
        namespace = self._namespace_for_user(username)
        try:
            result = self._get_k3s_api().create_pod(
                owner=username,
                user_email=username,
                image=payload.image or self.settings.default_sandbox_image,
                namespace=namespace,
                sandbox_id=sandbox_id,
                pod_name=pod_name,
                gpu_count=payload.gpu_count,
                username=payload.sandbox_username,
                password=payload.sandbox_password,
                command=payload.command,
                args=payload.args,
                env=payload.env,
                cpu_request=payload.cpu_request,
                memory_request=payload.memory_request,
                pod_label=payload.pod_label,
                enable_nodeport=payload.enable_nodeport,
                wait_until_running=payload.wait_until_running,
            )
            services = [result['service']] if result.get('service') else []
            return SandboxResponse(
                sandbox_id=result['sandbox_id'],
                pod_name=result['pod_name'],
                namespace=result['namespace'],
                status=result['status'],
                image=result['image'],
                created_at=result['created_at'],
                access_hint=self._build_access_hint(services),
                owner=username,
                services=services,
            )
        except PodCreationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f'创建开发沙盒失败: {str(exc)}',
            ) from exc

    def list_sandboxes(self, username: str) -> list[SandboxResponse]:
        try:
            pods = self._get_k3s_api().get_user_pods(owner=username, namespace=self._namespace_for_user(username))
            items: list[SandboxResponse] = []
            for pod in pods:
                created_at_raw = pod.get('created_at') or pod.get('start_time')
                try:
                    created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.now(timezone.utc)
                except ValueError:
                    created_at = datetime.now(timezone.utc)

                services = pod.get('services') or []
                items.append(
                    SandboxResponse(
                        sandbox_id=pod.get('sandbox_id') or pod['pod_name'],
                        pod_name=pod['pod_name'],
                        namespace=pod['namespace'],
                        status=pod.get('status') or 'Unknown',
                        image=pod.get('image_name') or 'unknown',
                        created_at=created_at,
                        access_hint=self._build_access_hint(services),
                        owner=username,
                        services=services,
                    )
                )
            return sorted(items, key=lambda item: item.created_at, reverse=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'获取沙盒列表失败: {str(exc)}') from exc
