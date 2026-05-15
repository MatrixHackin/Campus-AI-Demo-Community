"""
Prometheus客户端模块
用于查询GPU利用率和显存使用情况，并提供缓存机制
"""
import requests
import time
import threading
from typing import Dict, List, Optional
from app.core.config import get_settings


class PrometheusClient:
    """Prometheus API客户端（带缓存）"""

    def __init__(self, prometheus_url: str = None, cache_ttl: int = 20):
        """
        初始化Prometheus客户端

        Args:
            prometheus_url: Prometheus服务地址，默认使用Config中的配置
            cache_ttl: 缓存过期时间（秒），默认20秒
        """
        self.prometheus_url = prometheus_url or get_settings().prometheus_url
        self.cache_ttl = cache_ttl

        # 缓存数据
        self._gpu_utilization_cache: Optional[Dict] = None
        self._gpu_memory_cache: Optional[Dict] = None
        self._cache_timestamp: float = 0

        # 线程锁
        self._lock = threading.Lock()

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._gpu_utilization_cache is None:
            return False
        elapsed = time.time() - self._cache_timestamp
        return elapsed < self.cache_ttl

    def query(self, query_string: str) -> Optional[Dict]:
        """
        执行PromQL查询

        Args:
            query_string: PromQL查询语句

        Returns:
            查询结果的JSON数据，失败返回None
        """
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            response = requests.get(url, params={'query': query_string}, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data.get('status') != 'success':
                print(f"Prometheus查询失败: {data}")
                return None

            return data.get('data', {})
        except Exception as e:
            print(f"查询Prometheus失败: {e}")
            return None

    def _refresh_cache(self):
        """刷新缓存数据（内部方法）"""
        try:
            # 查询GPU利用率
            gpu_util = self._query_gpu_utilization()
            # 查询GPU显存
            gpu_mem = self._query_gpu_memory_usage()

            # 更新缓存
            with self._lock:
                self._gpu_utilization_cache = gpu_util
                self._gpu_memory_cache = gpu_mem
                self._cache_timestamp = time.time()
            return True
        except Exception as e:
            print(f"刷新缓存失败: {e}")
            return False

    def _query_gpu_utilization(self) -> Dict[str, List[Dict]]:
        """
        查询GPU利用率（无缓存，内部方法）

        Returns:
            GPU利用率数据
        """
        query = 'DCGM_FI_DEV_GPU_UTIL'
        data = self.query(query)

        if not data or 'result' not in data:
            return {}

        # 按节点分组
        node_gpus = {}
        for item in data['result']:
            metric = item.get('metric', {})
            value = item.get('value', [None, '0'])

            node_name = metric.get('Hostname', metric.get('kubernetes_node', 'unknown'))
            gpu_index = metric.get('gpu', metric.get('device', 'unknown'))
            gpu_uuid = metric.get('UUID', metric.get('uuid', ''))

            try:
                utilization = float(value[1])
            except (ValueError, IndexError, TypeError):
                utilization = 0.0

            if node_name not in node_gpus:
                node_gpus[node_name] = []

            node_gpus[node_name].append({
                'gpu_index': gpu_index,
                'utilization': utilization,
                'uuid': gpu_uuid
            })

        # 按GPU索引排序
        for node_name in node_gpus:
            node_gpus[node_name].sort(key=lambda x: x['gpu_index'])

        return node_gpus

    def get_gpu_utilization(self, use_cache: bool = True) -> Dict[str, List[Dict]]:
        """
        获取所有GPU的利用率（带缓存）

        Args:
            use_cache: 是否使用缓存，默认True

        Returns:
            字典，key为节点名，value为该节点上的GPU列表
            例如: {
                'node1': [
                    {'gpu_index': '0', 'utilization': 50.0, 'uuid': 'GPU-xxx'},
                    {'gpu_index': '1', 'utilization': 80.0, 'uuid': 'GPU-yyy'}
                ]
            }
        """
        # 如果使用缓存且缓存有效，直接返回
        if use_cache and self._is_cache_valid():
            return self._gpu_utilization_cache

        # 刷新缓存
        if self._refresh_cache():
            return self._gpu_utilization_cache

        # 刷新失败，返回旧缓存或空字典
        return self._gpu_utilization_cache or {}

    def _query_gpu_memory_usage(self) -> Dict[str, List[Dict]]:
        """
        查询GPU显存使用情况（无缓存，内部方法）

        Returns:
            GPU显存使用数据
        """
        # 查询已用显存
        used_query = 'DCGM_FI_DEV_FB_USED'
        used_data = self.query(used_query)

        # 查询空闲显存
        free_query = 'DCGM_FI_DEV_FB_FREE'
        free_data = self.query(free_query)

        node_gpus = {}

        # 处理已用显存
        if used_data and 'result' in used_data:
            for item in used_data['result']:
                metric = item.get('metric', {})
                value = item.get('value', [None, '0'])

                node_name = metric.get('Hostname', metric.get('kubernetes_node', 'unknown'))
                gpu_index = metric.get('gpu', metric.get('device', 'unknown'))

                try:
                    memory_used_mb = float(value[1])
                except (ValueError, IndexError, TypeError):
                    memory_used_mb = 0.0

                if node_name not in node_gpus:
                    node_gpus[node_name] = {}
                if gpu_index not in node_gpus[node_name]:
                    node_gpus[node_name][gpu_index] = {}

                node_gpus[node_name][gpu_index]['memory_used_mb'] = memory_used_mb
                node_gpus[node_name][gpu_index]['gpu_index'] = gpu_index

        # 处理空闲显存
        if free_data and 'result' in free_data:
            for item in free_data['result']:
                metric = item.get('metric', {})
                value = item.get('value', [None, '0'])

                node_name = metric.get('Hostname', metric.get('kubernetes_node', 'unknown'))
                gpu_index = metric.get('gpu', metric.get('device', 'unknown'))

                try:
                    memory_free_mb = float(value[1])
                except (ValueError, IndexError, TypeError):
                    memory_free_mb = 0.0

                if node_name not in node_gpus:
                    node_gpus[node_name] = {}
                if gpu_index not in node_gpus[node_name]:
                    node_gpus[node_name][gpu_index] = {}

                node_gpus[node_name][gpu_index]['memory_free_mb'] = memory_free_mb
                node_gpus[node_name][gpu_index]['gpu_index'] = gpu_index

        # 转换为列表格式并排序
        result = {}
        for node_name, gpus_dict in node_gpus.items():
            result[node_name] = sorted(gpus_dict.values(), key=lambda x: x['gpu_index'])

        return result

    def get_gpu_memory_usage(self, use_cache: bool = True) -> Dict[str, List[Dict]]:
        """
        获取所有GPU的显存使用情况（带缓存）

        Args:
            use_cache: 是否使用缓存，默认True

        Returns:
            字典，key为节点名，value为该节点上的GPU显存使用列表
            例如: {
                'node1': [
                    {'gpu_index': '0', 'memory_used_mb': 1024.0, 'memory_free_mb': 15360.0},
                ]
            }
        """
        # 如果使用缓存且缓存有效，直接返回
        if use_cache and self._is_cache_valid():
            return self._gpu_memory_cache

        # 刷新缓存
        if self._refresh_cache():
            return self._gpu_memory_cache

        # 刷新失败，返回旧缓存或空字典
        return self._gpu_memory_cache or {}

    def get_low_utilization_gpu_count(self, threshold: float = 20.0) -> Dict[str, int]:
        """
        统计每个节点上低利用率GPU的数量（带缓存）

        Args:
            threshold: 利用率阈值，默认20%

        Returns:
            字典，key为节点名，value为低利用率GPU数量
            例如: {'kimi-a0967b': 3, 'lhm-2da5ab': 1}
        """
        gpu_utils = self.get_gpu_utilization(use_cache=True)

        if not gpu_utils:
            return {}

        result = {}
        for node_name, gpus in gpu_utils.items():
            low_util_count = sum(1 for gpu in gpus if gpu['utilization'] < threshold)
            result[node_name] = low_util_count

        return result

    def get_node_average_gpu_utilization(self, node_name: str) -> float:
        """
        获取指定节点的平均GPU利用率

        Args:
            node_name: 节点名称

        Returns:
            平均利用率 (0-100)，如果查询失败返回100.0（最坏情况）
        """
        all_gpus = self.get_gpu_utilization()

        if node_name not in all_gpus or not all_gpus[node_name]:
            # 如果查询不到数据，返回100表示最坏情况（避免调度到有问题的节点）
            return 100.0

        gpus = all_gpus[node_name]
        utilizations = [gpu['utilization'] for gpu in gpus]

        if not utilizations:
            return 100.0

        return sum(utilizations) / len(utilizations)


if __name__ == '__main__':
    # 测试代码
    import time

    client = PrometheusClient(cache_ttl=20)

    print("=== 第一次查询（从Prometheus获取）===")
    start = time.time()
    gpu_utils = client.get_gpu_utilization()
    elapsed1 = (time.time() - start) * 1000
    print(f"耗时: {elapsed1:.2f}ms")

    for node, gpus in list(gpu_utils.items())[:2]:  # 只显示前2个节点
        print(f"\n节点: {node}")
        for gpu in gpus[:3]:  # 每个节点只显示前3个GPU
            print(f"  GPU{gpu['gpu_index']}: {gpu['utilization']:.1f}%")

    print("\n=== 第二次查询（从缓存获取）===")
    start = time.time()
    gpu_utils = client.get_gpu_utilization()
    elapsed2 = (time.time() - start) * 1000
    print(f"耗时: {elapsed2:.2f}ms")
    print(f"缓存加速: {elapsed1/elapsed2:.0f}x")

    print("\n=== 低利用率(<20%)GPU统计 ===")
    low_util = client.get_low_utilization_gpu_count(threshold=20.0)
    for node, count in low_util.items():
        print(f"{node}: {count}个GPU")

