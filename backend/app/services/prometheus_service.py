from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from app.core.config import Settings

logger = logging.getLogger(__name__)

BYTES_PER_GIB = 1024 ** 3


@dataclass(slots=True)
class PodUsageWindow:
    window_start: datetime
    window_end: datetime
    duration_seconds: float
    cpu_core_seconds: float = 0.0
    cpu_max_cores: float = 0.0
    memory_avg_bytes: float = 0.0
    memory_max_bytes: float = 0.0
    network_rx_bytes: float = 0.0
    network_tx_bytes: float = 0.0
    complete: bool = True


class PrometheusService:
    """Prometheus 查询封装。

    资源消耗统计采用“窗口增量”方式：
    - CPU / 网络是 counter，使用 increase(...) 计算窗口内增量，适合累加。
    - 内存是 gauge，使用 query_range 采样后计算窗口平均和峰值，再按窗口时长累加 GB-hours。
    - CPU 峰值使用 5m rate 的 query_range 最大值，避免瞬时 counter 不可直接取 max。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.prometheus_url.strip())

    def aggregate_pod_usage_window(
        self,
        *,
        namespace: str,
        pod_name: str,
        window_start: datetime,
        window_end: datetime,
    ) -> PodUsageWindow:
        window_start = self._ensure_utc(window_start)
        window_end = self._ensure_utc(window_end)
        if window_end <= window_start:
            return PodUsageWindow(window_start=window_start, window_end=window_end, duration_seconds=0)

        complete = True
        retention_start = window_end.timestamp() - self.settings.prometheus_retention_seconds
        if window_start.timestamp() < retention_start:
            window_start = datetime.fromtimestamp(retention_start, tz=timezone.utc)
            complete = False

        duration_seconds = max(0.0, window_end.timestamp() - window_start.timestamp())
        if duration_seconds <= 0:
            return PodUsageWindow(
                window_start=window_start,
                window_end=window_end,
                duration_seconds=0,
                complete=False,
            )

        duration = self._prom_duration(duration_seconds)
        end_timestamp = window_end.timestamp()
        cpu_increase_query = (
            'sum(increase(container_cpu_usage_seconds_total{'
            f'namespace="{namespace}",pod="{pod_name}",container!="POD",image!=""'
            f'}}[{duration}]))'
        )
        network_rx_query = (
            'sum(increase(container_network_receive_bytes_total{'
            f'namespace="{namespace}",pod="{pod_name}"'
            f'}}[{duration}]))'
        )
        network_tx_query = (
            'sum(increase(container_network_transmit_bytes_total{'
            f'namespace="{namespace}",pod="{pod_name}"'
            f'}}[{duration}]))'
        )
        cpu_rate_query = (
            'sum(rate(container_cpu_usage_seconds_total{'
            f'namespace="{namespace}",pod="{pod_name}",container!="POD",image!=""'
            '}[5m]))'
        )
        memory_query = (
            'sum(container_memory_working_set_bytes{'
            f'namespace="{namespace}",pod="{pod_name}",container!="POD",image!=""'
            '})'
        )

        cpu_core_seconds = self._query_scalar(cpu_increase_query, time=end_timestamp)
        network_rx_bytes = self._query_scalar(network_rx_query, time=end_timestamp)
        network_tx_bytes = self._query_scalar(network_tx_query, time=end_timestamp)
        step = self._range_step(duration_seconds)
        cpu_rate_values = self._query_range_values(
            cpu_rate_query,
            start=window_start.timestamp(),
            end=end_timestamp,
            step=step,
        )
        memory_values = self._query_range_values(
            memory_query,
            start=window_start.timestamp(),
            end=end_timestamp,
            step=step,
        )

        return PodUsageWindow(
            window_start=window_start,
            window_end=window_end,
            duration_seconds=duration_seconds,
            cpu_core_seconds=max(0.0, cpu_core_seconds),
            cpu_max_cores=max(cpu_rate_values) if cpu_rate_values else 0.0,
            memory_avg_bytes=(sum(memory_values) / len(memory_values)) if memory_values else 0.0,
            memory_max_bytes=max(memory_values) if memory_values else 0.0,
            network_rx_bytes=max(0.0, network_rx_bytes),
            network_tx_bytes=max(0.0, network_tx_bytes),
            complete=complete,
        )

    def pod_usage_trend(self, *, namespace: str, pod_name: str, minutes: int = 5) -> dict[str, Any]:
        """查询 Pod 最近一段时间的趋势指标。

        趋势图只用于用户点击“查看资源消耗”后的短窗口展示，不写数据库：
        - CPU 使用 1 分钟 rate，单位 cores；
        - 内存使用 working_set gauge，单位 bytes；
        - 网络使用 1 分钟 rate，单位 bytes/s。
        """
        window_seconds = max(60, min(int(minutes * 60), self.settings.prometheus_retention_seconds))
        window_end = datetime.now(timezone.utc)
        window_start = datetime.fromtimestamp(window_end.timestamp() - window_seconds, tz=timezone.utc)
        complete = True
        retention_start = window_end.timestamp() - self.settings.prometheus_retention_seconds
        if window_start.timestamp() < retention_start:
            window_start = datetime.fromtimestamp(retention_start, tz=timezone.utc)
            complete = False

        start_timestamp = window_start.timestamp()
        end_timestamp = window_end.timestamp()
        step = max(5, int(self.settings.prometheus_trend_step_seconds))
        selectors = f'namespace="{namespace}",pod="{pod_name}"'
        workload_selectors = f'{selectors},container!="POD",image!=""'
        metric_queries = {
            'cpu': {
                'label': 'CPU',
                'unit': 'cores',
                'query': f'sum(rate(container_cpu_usage_seconds_total{{{workload_selectors}}}[1m]))',
            },
            'memory': {
                'label': '内存',
                'unit': 'bytes',
                'query': f'sum(container_memory_working_set_bytes{{{workload_selectors}}})',
            },
            'network_rx': {
                'label': '网络接收',
                'unit': 'bytes/s',
                'query': f'sum(rate(container_network_receive_bytes_total{{{selectors}}}[1m]))',
            },
            'network_tx': {
                'label': '网络发送',
                'unit': 'bytes/s',
                'query': f'sum(rate(container_network_transmit_bytes_total{{{selectors}}}[1m]))',
            },
        }

        return {
            'window_seconds': int(end_timestamp - start_timestamp),
            'step_seconds': step,
            'complete': complete,
            'series': [
                {
                    'key': key,
                    'label': spec['label'],
                    'unit': spec['unit'],
                    'current_value': max(0.0, self._query_scalar(spec['query'], time=end_timestamp)),
                    'points': self._query_range_points(
                        spec['query'],
                        start=start_timestamp,
                        end=end_timestamp,
                        step=step,
                    ),
                }
                for key, spec in metric_queries.items()
            ],
        }

    def _query_scalar(self, query: str, *, time: float) -> float:
        data = self._request('/api/v1/query', params={'query': query, 'time': f'{time:.3f}'})
        result = data.get('data', {}).get('result') or []
        if not result:
            return 0.0
        try:
            return float(result[0]['value'][1])
        except (KeyError, IndexError, TypeError, ValueError):
            return 0.0

    def _query_range_values(self, query: str, *, start: float, end: float, step: int) -> list[float]:
        return [point['value'] for point in self._query_range_points(query, start=start, end=end, step=step)]

    def _query_range_points(self, query: str, *, start: float, end: float, step: int) -> list[dict[str, float]]:
        data = self._request(
            '/api/v1/query_range',
            params={
                'query': query,
                'start': f'{start:.3f}',
                'end': f'{end:.3f}',
                'step': str(step),
            },
        )
        result = data.get('data', {}).get('result') or []
        points: list[dict[str, float]] = []
        for series in result:
            for timestamp, raw_value in series.get('values') or []:
                try:
                    ts = float(timestamp)
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    points.append({'timestamp': ts, 'value': max(0.0, value)})
        return points

    def _request(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError('资源监控暂不可用')

        response = requests.get(
            f'{self.settings.prometheus_url.rstrip("/")}{path}',
            params=params,
            timeout=self.settings.prometheus_query_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'success':
            raise RuntimeError('资源监控查询失败')
        return data

    def _range_step(self, duration_seconds: float) -> int:
        max_points = max(1, self.settings.prometheus_query_range_max_points)
        min_step = max(1, self.settings.prometheus_query_range_min_step_seconds)
        return max(min_step, int(math.ceil(duration_seconds / max_points)))

    @staticmethod
    def _prom_duration(duration_seconds: float) -> str:
        return f'{max(1, int(math.ceil(duration_seconds)))}s'

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
