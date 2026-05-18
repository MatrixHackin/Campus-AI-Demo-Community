from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.services.container_repository import ContainerRepository
from app.services.container_usage_log_repository import ContainerUsageLogRepository, mysql_datetime
from app.services.prometheus_service import BYTES_PER_GIB, PodUsageWindow, PrometheusService

logger = logging.getLogger(__name__)


class ContainerUsageService:
    """容器资源消耗汇总服务。

    定时任务和删除容器时复用同一套逻辑：
    - 每次只统计 metrics_last_collected_at 到当前时间的窗口；
    - CPU / 网络累加；
    - 内存按窗口时长加权，保留平均、峰值和 GB-hours；
    - 如果窗口起点早于 Prometheus retention，则标记 metrics_complete=false。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prometheus = PrometheusService(settings)
        self.log_repository = ContainerUsageLogRepository(settings)
        self.container_repository = ContainerRepository(settings)
        self._core_v1 = None

    def collect_all_running(self) -> dict[str, Any]:
        pods = self._core().list_pod_for_all_namespaces(label_selector='app=campus-ai-devbox').items
        results = []
        for pod in pods:
            if pod.metadata and pod.metadata.deletion_timestamp:
                continue
            if not pod.status or pod.status.phase != 'Running':
                continue
            try:
                results.append(self.collect_pod(pod=pod, final=False))
            except Exception as exc:
                pod_name = pod.metadata.name if pod.metadata else 'unknown'
                logger.warning('汇总运行中容器 %s 资源消耗失败：%s', pod_name, exc)
                results.append({'pod_name': pod_name, 'status': 'error', 'message': str(exc)})
        return {
            'collected': sum(1 for item in results if item.get('status') != 'error'),
            'failed': sum(1 for item in results if item.get('status') == 'error'),
            'results': results,
        }

    def list_namespace_usage(self, namespace: str) -> dict[str, Any]:
        pods = self._core().list_namespaced_pod(namespace=namespace, label_selector='app=campus-ai-devbox').items
        return {
            'namespace': namespace,
            'apps': [self._usage_item_from_pod(pod) for pod in pods if pod.metadata and not pod.metadata.deletion_timestamp],
        }

    def collect_pod_by_name(self, *, namespace: str, pod_name: str, final: bool = False) -> dict[str, Any]:
        pod = self._core().read_namespaced_pod(namespace=namespace, name=pod_name)
        return self.collect_pod(pod=pod, final=final)

    def get_pod_usage_trend(self, *, namespace: str, pod_name: str, minutes: int = 5) -> dict[str, Any]:
        from kubernetes.client.rest import ApiException

        try:
            pod = self._core().read_namespaced_pod(namespace=namespace, name=pod_name)
        except ApiException as exc:
            if exc.status == 404:
                raise FileNotFoundError('容器不存在') from exc
            raise RuntimeError(f'查询容器失败：{exc.reason or exc.status}') from exc
        metadata = pod.metadata
        if not metadata or metadata.deletion_timestamp:
            raise FileNotFoundError('容器不存在或正在删除')
        labels = metadata.labels or {}
        if labels.get('app') != 'campus-ai-devbox':
            raise PermissionError('无权查看该容器资源消耗')

        trend = self.prometheus.pod_usage_trend(namespace=namespace, pod_name=pod_name, minutes=minutes)
        return {
            'pod_name': pod_name,
            'app_name': labels.get('campus-ai/app-name'),
            'status': pod.status.phase if pod.status and pod.status.phase else 'Unknown',
            **trend,
        }

    def collect_pod(self, *, pod, final: bool = False, collected_at: datetime | None = None) -> dict[str, Any]:
        now = self._ensure_utc(collected_at or datetime.now(timezone.utc))
        metadata = pod.metadata
        spec = pod.spec
        status = pod.status
        if not metadata or not metadata.name or not metadata.namespace:
            raise RuntimeError('Pod 元数据不完整，无法汇总资源消耗')

        pod_name = metadata.name
        namespace = metadata.namespace
        start_time = self._ensure_utc(status.start_time) if status and status.start_time else now
        labels = metadata.labels or {}
        containers = spec.containers if spec and spec.containers else []
        container = containers[0] if containers else None
        image = container.image if container else ''

        existing = self.log_repository.get_by_pod_name(pod_name)
        last_collected_at = self._ensure_utc(existing['metrics_last_collected_at']) if existing and existing.get('metrics_last_collected_at') else None
        window_start = last_collected_at or start_time
        if window_start < start_time:
            window_start = start_time

        usage_window = None
        if now > window_start:
            usage_window = self.prometheus.aggregate_pod_usage_window(
                namespace=namespace,
                pod_name=pod_name,
                window_start=window_start,
                window_end=now,
            )

        values = self._build_log_values(
            existing=existing,
            pod=pod,
            usage_window=usage_window,
            final=final,
            now=now,
            app_name=labels.get('campus-ai/app-name'),
            image=image,
        )
        self.log_repository.upsert_usage_log(values)
        return {
            'pod_name': pod_name,
            'namespace': namespace,
            'status': values['status'],
            'window_start': usage_window.window_start.isoformat() if usage_window else None,
            'window_end': usage_window.window_end.isoformat() if usage_window else None,
            'cpu_core_seconds': values['cpu_core_seconds'],
            'network_rx_bytes': values['network_rx_bytes'],
            'network_tx_bytes': values['network_tx_bytes'],
            'metrics_complete': bool(values['metrics_complete']),
        }

    def _usage_item_from_pod(self, pod) -> dict[str, Any]:
        metadata = pod.metadata
        spec = pod.spec
        status = pod.status
        pod_name = metadata.name
        namespace = metadata.namespace
        labels = metadata.labels or {}
        containers = spec.containers if spec and spec.containers else []
        image = containers[0].image if containers else ''
        now = datetime.now(timezone.utc)
        start_time = self._ensure_utc(status.start_time) if status and status.start_time else now
        # 当前指标使用最近 5 分钟窗口；新建不足 5 分钟的 Pod 从 start_time 开始。
        five_minutes_ago = datetime.fromtimestamp(now.timestamp() - 300, tz=timezone.utc)
        window_start = max(start_time, five_minutes_ago)
        try:
            usage_window = self.prometheus.aggregate_pod_usage_window(
                namespace=namespace,
                pod_name=pod_name,
                window_start=window_start,
                window_end=now,
            )
            window_seconds = usage_window.duration_seconds or 1
            current = {
                'cpu_cores': usage_window.cpu_core_seconds / window_seconds,
                'cpu_max_cores': usage_window.cpu_max_cores,
                'memory_bytes': int(usage_window.memory_avg_bytes),
                'memory_max_bytes': int(usage_window.memory_max_bytes),
                'network_rx_bps': usage_window.network_rx_bytes / window_seconds,
                'network_tx_bps': usage_window.network_tx_bytes / window_seconds,
            }
        except Exception as exc:
            logger.warning('查询 Pod %s/%s 当前资源指标失败：%s', namespace, pod_name, exc)
            current = {
                'cpu_cores': 0,
                'cpu_max_cores': 0,
                'memory_bytes': 0,
                'memory_max_bytes': 0,
                'network_rx_bps': 0,
                'network_tx_bps': 0,
            }

        existing = self.log_repository.get_by_pod_name(pod_name) or {}
        return {
            'pod_name': pod_name,
            'app_name': labels.get('campus-ai/app-name') or existing.get('app_name'),
            'status': status.phase if status and status.phase else 'Unknown',
            'node_name': spec.node_name if spec else None,
            'image': image,
            'start_time': start_time.isoformat(),
            'duration': int((now - start_time).total_seconds()),
            'cpu_limit_cores': self._cpu_limit_cores(pod),
            'memory_limit_bytes': self._memory_limit_bytes(pod),
            'current': current,
            'total': {
                'cpu_core_seconds': float(existing.get('cpu_core_seconds') or 0),
                'memory_gb_hours': float(existing.get('memory_gb_hours') or 0),
                'network_rx_bytes': int(existing.get('network_rx_bytes') or 0),
                'network_tx_bytes': int(existing.get('network_tx_bytes') or 0),
                'metrics_last_collected_at': existing.get('metrics_last_collected_at').isoformat()
                if existing.get('metrics_last_collected_at') else None,
                'metrics_complete': bool(existing.get('metrics_complete', True)),
            },
        }

    def _build_log_values(
        self,
        *,
        existing: dict | None,
        pod,
        usage_window: PodUsageWindow | None,
        final: bool,
        now: datetime,
        app_name: str | None,
        image: str,
    ) -> dict[str, Any]:
        metadata = pod.metadata
        spec = pod.spec
        status = pod.status
        pod_name = metadata.name
        namespace = metadata.namespace
        start_time = self._ensure_utc(status.start_time) if status and status.start_time else now
        node_name = spec.node_name if spec else None
        user_profile = self.log_repository.find_user_profile_by_namespace(namespace)
        record = self.container_repository.get_container_record(pod_name=pod_name)
        owner_username = (record or {}).get('username') or user_profile.get('owner_username')

        old_collected_seconds = self._float(existing, 'metrics_collected_seconds')
        old_cpu_core_seconds = self._float(existing, 'cpu_core_seconds')
        old_cpu_max = self._float(existing, 'cpu_max_cores')
        old_memory_byte_seconds = self._float(existing, 'memory_byte_seconds')
        old_memory_max = self._float(existing, 'memory_max_bytes')
        old_memory_gb_hours = self._float(existing, 'memory_gb_hours')
        old_network_rx = self._float(existing, 'network_rx_bytes')
        old_network_tx = self._float(existing, 'network_tx_bytes')
        old_window_count = int(existing.get('metrics_window_count') or 0) if existing else 0
        old_complete = bool(existing.get('metrics_complete', True)) if existing else True

        window_seconds = usage_window.duration_seconds if usage_window else 0.0
        collected_seconds = old_collected_seconds + window_seconds
        cpu_core_seconds = old_cpu_core_seconds + (usage_window.cpu_core_seconds if usage_window else 0.0)
        memory_byte_seconds = old_memory_byte_seconds + (
            usage_window.memory_avg_bytes * window_seconds if usage_window else 0.0
        )
        memory_gb_hours = old_memory_gb_hours + (
            usage_window.memory_avg_bytes / BYTES_PER_GIB * window_seconds / 3600 if usage_window else 0.0
        )
        network_rx = old_network_rx + (usage_window.network_rx_bytes if usage_window else 0.0)
        network_tx = old_network_tx + (usage_window.network_tx_bytes if usage_window else 0.0)
        memory_avg = memory_byte_seconds / collected_seconds if collected_seconds > 0 else 0.0
        cpu_avg = cpu_core_seconds / collected_seconds if collected_seconds > 0 else 0.0
        complete = old_complete and (usage_window.complete if usage_window else True)
        first_collected_at = existing.get('metrics_first_collected_at') if existing else None
        if not first_collected_at and usage_window and usage_window.duration_seconds > 0:
            first_collected_at = usage_window.window_start
        last_collected_at = existing.get('metrics_last_collected_at') if existing else None
        if usage_window and usage_window.duration_seconds > 0:
            last_collected_at = usage_window.window_end

        duration = max(0, int((now - start_time).total_seconds()))
        return {
            'pod_name': pod_name,
            'app_name': app_name or (record or {}).get('app_name'),
            'namespace': namespace,
            'gpu_count': 0,
            'start_time': mysql_datetime(start_time),
            'node_name': node_name,
            'duration': duration,
            'user_email': user_profile.get('owner_email'),
            'user_name': user_profile.get('user_name') or owner_username,
            'owner_username': owner_username,
            'owner_email': user_profile.get('owner_email'),
            'image': image,
            'status': 'deleted' if final else 'running',
            'deleted_at': mysql_datetime(now) if final else None,
            'cpu_limit_cores': self._cpu_limit_cores(pod),
            'memory_limit_bytes': self._memory_limit_bytes(pod),
            'cpu_core_seconds': cpu_core_seconds,
            'cpu_avg_cores': cpu_avg,
            'cpu_max_cores': max(old_cpu_max, usage_window.cpu_max_cores if usage_window else 0.0),
            'memory_avg_bytes': int(memory_avg),
            'memory_max_bytes': int(max(old_memory_max, usage_window.memory_max_bytes if usage_window else 0.0)),
            'memory_byte_seconds': memory_byte_seconds,
            'memory_gb_hours': memory_gb_hours,
            'network_rx_bytes': int(network_rx),
            'network_tx_bytes': int(network_tx),
            'metrics_first_collected_at': mysql_datetime(self._ensure_utc(first_collected_at)) if first_collected_at else None,
            'metrics_last_collected_at': mysql_datetime(self._ensure_utc(last_collected_at)) if last_collected_at else None,
            'metrics_window_count': old_window_count + (1 if usage_window and usage_window.duration_seconds > 0 else 0),
            'metrics_collected_seconds': int(collected_seconds),
            'metrics_complete': 1 if complete else 0,
        }

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
    def _float(row: dict | None, key: str) -> float:
        if not row:
            return 0.0
        value = row.get(key)
        if value is None:
            return 0.0
        return float(value)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _cpu_limit_cores(cls, pod) -> float | None:
        value = cls._first_limit_value(pod, 'cpu')
        if value is None:
            return None
        raw = str(value)
        if raw.endswith('m'):
            return float(raw[:-1]) / 1000
        try:
            return float(raw)
        except ValueError:
            return None

    @classmethod
    def _memory_limit_bytes(cls, pod) -> int | None:
        value = cls._first_limit_value(pod, 'memory')
        if value is None:
            return None
        return cls._parse_k8s_memory(str(value))

    @staticmethod
    def _first_limit_value(pod, resource_name: str):
        containers = pod.spec.containers if pod.spec and pod.spec.containers else []
        if not containers:
            return None
        resources = containers[0].resources
        limits = resources.limits if resources and resources.limits else {}
        return limits.get(resource_name)

    @staticmethod
    def _parse_k8s_memory(raw: str) -> int | None:
        match = re.fullmatch(r'([0-9.]+)([KMGTE]i?|[kMGTPE])?', raw)
        if not match:
            return None
        value = float(match.group(1))
        suffix = match.group(2) or ''
        factors = {
            '': 1,
            'Ki': 1024,
            'Mi': 1024 ** 2,
            'Gi': 1024 ** 3,
            'Ti': 1024 ** 4,
            'Pi': 1024 ** 5,
            'Ei': 1024 ** 6,
            'k': 1000,
            'M': 1000 ** 2,
            'G': 1000 ** 3,
            'T': 1000 ** 4,
            'P': 1000 ** 5,
            'E': 1000 ** 6,
        }
        return int(value * factors.get(suffix, 1))
