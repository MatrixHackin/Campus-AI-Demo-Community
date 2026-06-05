from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import signal
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


TARGET_APPS = {
    'codex-claude-notifier': {
        'namespace': '50013734',
        'pod': 'campus-devbox-f0828a1f',
        'node': 'cnode07',
    },
    'colorpicker': {
        'namespace': '50030457',
        'pod': 'campus-devbox-22a7eb2b',
        'node': 'cnode07',
    },
    'tex2svg': {
        'namespace': 'gzl0001884',
        'pod': 'campus-devbox-7b4c0690',
        'node': 'cnode07',
    },
    'time-converter': {
        'namespace': '50039790',
        'pod': 'campus-devbox-fdf24445',
        'node': 'cnode08',
    },
    'fastqr': {
        'namespace': '50031097',
        'pod': 'campus-devbox-97be2f90',
        'node': 'cnode07',
    },
}

LATEX_SAMPLES = [
    r'E = mc^2',
    r'\int_{0}^{\infty} e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}',
    r'\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}',
    r'\nabla \cdot \vec{E} = \frac{\rho}{\epsilon_0}',
    r'\frac{\partial u}{\partial t} = \alpha \nabla^2 u',
    r'\begin{bmatrix} a & b \\ c & d \end{bmatrix}^{-1}'
    r'= \frac{1}{ad-bc}\begin{bmatrix} d & -b \\ -c & a \end{bmatrix}',
]

TIME_ZONES = [
    ('Asia/Shanghai', 'UTC'),
    ('Asia/Shanghai', 'America/New_York'),
    ('UTC', 'Asia/Tokyo'),
    ('Europe/London', 'Asia/Shanghai'),
    ('America/Los_Angeles', 'Asia/Hong_Kong'),
]


@dataclass(slots=True)
class RequestRecord:
    scenario: str
    path: str
    status: int
    ok: bool
    latency_ms: float
    bytes_read: int


@dataclass(slots=True)
class StageStats:
    name: str
    records: list[RequestRecord] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def record(self, item: RequestRecord) -> None:
        self.records.append(item)

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.records if not item.ok)

    @property
    def failure_rate(self) -> float:
        return self.failed / self.total if self.total else 0.0

    @property
    def rps(self) -> float:
        end = self.finished_at or time.time()
        elapsed = max(0.001, end - self.started_at)
        return self.total / elapsed

    def latencies(self) -> list[float]:
        return [item.latency_ms for item in self.records if item.latency_ms >= 0]

    def percentile(self, percent: float) -> float:
        values = sorted(self.latencies())
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percent))))
        return values[index]

    def by_scenario(self) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[RequestRecord]] = {}
        for item in self.records:
            grouped.setdefault(item.scenario, []).append(item)
        result: dict[str, dict[str, Any]] = {}
        for name, records in grouped.items():
            latencies = sorted(item.latency_ms for item in records)
            result[name] = {
                'total': len(records),
                'failed': sum(1 for item in records if not item.ok),
                'failure_rate': sum(1 for item in records if not item.ok) / len(records),
                'p50_ms': percentile_values(latencies, 0.50),
                'p95_ms': percentile_values(latencies, 0.95),
                'p99_ms': percentile_values(latencies, 0.99),
                'bytes': sum(item.bytes_read for item in records),
            }
        return result

    def summary(self) -> dict[str, Any]:
        latencies = sorted(self.latencies())
        statuses: dict[str, int] = {}
        for item in self.records:
            statuses[str(item.status)] = statuses.get(str(item.status), 0) + 1
        return {
            'name': self.name,
            'total': self.total,
            'failed': self.failed,
            'failure_rate': self.failure_rate,
            'rps': self.rps,
            'p50_ms': percentile_values(latencies, 0.50),
            'p95_ms': percentile_values(latencies, 0.95),
            'p99_ms': percentile_values(latencies, 0.99),
            'mean_ms': statistics.fmean(latencies) if latencies else 0.0,
            'statuses': statuses,
            'by_scenario': self.by_scenario(),
        }


def percentile_values(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percent))))
    return values[index]


def parse_stages(value: str) -> list[tuple[int, int]]:
    stages: list[tuple[int, int]] = []
    for item in value.split(','):
        item = item.strip()
        if not item:
            continue
        concurrency, seconds = item.split(':', 1)
        stages.append((int(concurrency), int(seconds)))
    return stages


def parse_http_response(raw: bytes) -> tuple[int, int]:
    header, _, body = raw.partition(b'\r\n\r\n')
    status_line = header.splitlines()[0].decode('iso-8859-1', errors='replace') if header else ''
    parts = status_line.split(' ', 2)
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    return status, len(body)


async def request_once(
    *,
    host: str,
    port: int,
    request_host: str,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b'',
    timeout: float,
) -> tuple[int, int, float]:
    started = time.perf_counter()
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        request_headers = {
            'Host': request_host,
            'User-Agent': 'campus-ai-app-market-loadtest/1.0',
            'Accept': '*/*',
            'Connection': 'close',
        }
        if headers:
            request_headers.update(headers)
        if body:
            request_headers['Content-Length'] = str(len(body))
        request_lines = [f'{method} {path} HTTP/1.1']
        request_lines.extend(f'{key}: {value}' for key, value in request_headers.items())
        raw_request = '\r\n'.join(request_lines).encode('utf-8') + b'\r\n\r\n' + body
        writer.write(raw_request)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        raw_response = await asyncio.wait_for(reader.read(), timeout=timeout)
        status, bytes_read = parse_http_response(raw_response)
        return status, bytes_read, (time.perf_counter() - started) * 1000
    finally:
        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def record_request(
    stats: StageStats,
    *,
    scenario: str,
    host: str,
    port: int,
    request_host: str,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b'',
    timeout: float,
) -> bool:
    try:
        status, bytes_read, latency_ms = await request_once(
            host=host,
            port=port,
            request_host=request_host,
            method=method,
            path=path,
            headers=headers,
            body=body,
            timeout=timeout,
        )
        ok = 200 <= status < 500
        stats.record(
            RequestRecord(
                scenario=scenario,
                path=path,
                status=status,
                ok=ok,
                latency_ms=latency_ms,
                bytes_read=bytes_read,
            )
        )
        return ok
    except Exception:
        stats.record(
            RequestRecord(
                scenario=scenario,
                path=path,
                status=0,
                ok=False,
                latency_ms=-1,
                bytes_read=0,
            )
        )
        return False


async def run_static_scenario(args: argparse.Namespace, stats: StageStats, assets: dict[str, list[str]]) -> None:
    app_name = random.choice(list(TARGET_APPS))
    base_path = f'/apps/{app_name}'
    await record_request(
        stats,
        scenario=f'static:{app_name}',
        host=args.http_host,
        port=args.http_port,
        request_host=args.request_host,
        method='GET',
        path=base_path,
        timeout=args.request_timeout,
    )
    for asset_path in assets.get(app_name, [])[: args.max_assets_per_page]:
        await record_request(
            stats,
            scenario=f'asset:{app_name}',
            host=args.http_host,
            port=args.http_port,
            request_host=args.request_host,
            method='GET',
            path=asset_path,
            timeout=args.request_timeout,
        )


async def run_tex2svg_scenario(args: argparse.Namespace, stats: StageStats) -> None:
    body = json.dumps({'latex': random.choice(LATEX_SAMPLES), 'display': True}).encode('utf-8')
    await record_request(
        stats,
        scenario='dynamic:tex2svg',
        host=args.http_host,
        port=args.http_port,
        request_host=args.request_host,
        method='POST',
        path='/apps/tex2svg/api/convert',
        headers={'Content-Type': 'application/json'},
        body=body,
        timeout=args.request_timeout,
    )


async def run_time_converter_scenario(args: argparse.Namespace, stats: StageStats) -> None:
    source_zone, target_zone = random.choice(TIME_ZONES)
    minute = random.randint(0, 59)
    hour = random.randint(0, 23)
    body = urlencode(
        {
            'time': f'2026-06-01T{hour:02d}:{minute:02d}',
            'source_zone': source_zone,
            'target_zone': target_zone,
        }
    ).encode('utf-8')
    await record_request(
        stats,
        scenario='dynamic:time-converter',
        host=args.http_host,
        port=args.http_port,
        request_host=args.request_host,
        method='POST',
        path='/apps/time-converter/convert',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        body=body,
        timeout=args.request_timeout,
    )


async def worker(
    worker_id: int,
    args: argparse.Namespace,
    stats: StageStats,
    assets: dict[str, list[str]],
    stop_event: asyncio.Event,
) -> None:
    random.seed(args.seed + worker_id)
    scenario_names = ['static', 'tex2svg', 'time-converter']
    scenario_weights = [args.static_weight, args.tex2svg_weight, args.time_weight]
    while not stop_event.is_set():
        scenario = random.choices(scenario_names, weights=scenario_weights, k=1)[0]
        if scenario == 'static':
            await run_static_scenario(args, stats, assets)
        elif scenario == 'tex2svg':
            await run_tex2svg_scenario(args, stats)
        else:
            await run_time_converter_scenario(args, stats)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=random.uniform(args.think_min_seconds, args.think_max_seconds),
            )
        except TimeoutError:
            continue


def fetch_page_for_assets(args: argparse.Namespace, app_name: str) -> str:
    req = Request(
        f'http://{args.http_host}:{args.http_port}/apps/{app_name}',
        headers={'Host': args.request_host, 'User-Agent': 'campus-ai-app-market-loadtest/asset-discovery'},
    )
    with urlopen(req, timeout=args.request_timeout) as response:
        return response.read().decode('utf-8', errors='replace')


def discover_assets(args: argparse.Namespace) -> dict[str, list[str]]:
    assets: dict[str, list[str]] = {}
    attr_pattern = re.compile(r'''(?:src|href)=["']([^"']+)["']''', re.IGNORECASE)
    for app_name in TARGET_APPS:
        try:
            html = fetch_page_for_assets(args, app_name)
        except Exception:
            assets[app_name] = []
            continue
        base_url = f'http://{args.request_host}/apps/{app_name}/'
        app_assets: list[str] = []
        for match in attr_pattern.finditer(html):
            value = match.group(1).strip()
            if not value or value.startswith(('data:', 'mailto:', '#')):
                continue
            parsed = urlparse(urljoin(base_url, value))
            if parsed.netloc and parsed.netloc != args.request_host:
                continue
            path = parsed.path
            if path.startswith(f'/apps/{app_name}/') and path != f'/apps/{app_name}/':
                app_assets.append(path)
        assets[app_name] = sorted(set(app_assets))
    return assets


def prom_query(prom_url: str, query: str) -> list[dict[str, Any]]:
    url = f'{prom_url.rstrip("/")}/api/v1/query?{urlencode({"query": query})}'
    req = Request(url, headers={'User-Agent': 'campus-ai-app-market-loadtest/prometheus'})
    with urlopen(req, timeout=5) as response:
        payload = json.loads(response.read().decode('utf-8'))
    if payload.get('status') != 'success':
        return []
    return payload.get('data', {}).get('result', [])


async def monitor_prometheus(
    args: argparse.Namespace,
    stage_name: str,
    samples: list[dict[str, Any]],
    stop_event: asyncio.Event,
    global_stop: asyncio.Event,
) -> None:
    if args.no_prometheus:
        return

    namespace_pattern = '|'.join(sorted({item['namespace'] for item in TARGET_APPS.values()}))
    pod_pattern = '|'.join(sorted({item['pod'] for item in TARGET_APPS.values()}))
    queries = {
        'target_pod_cpu_cores': (
            'sum by (namespace,pod) (rate(container_cpu_usage_seconds_total{'
            f'namespace=~"{namespace_pattern}",pod=~"{pod_pattern}",container!="",image!=""'
            '}[1m]))'
        ),
        'target_pod_memory_bytes': (
            'sum by (namespace,pod) (container_memory_working_set_bytes{'
            f'namespace=~"{namespace_pattern}",pod=~"{pod_pattern}",container!="",image!=""'
            '})'
        ),
        'target_pod_rx_bytes_per_second': (
            'sum by (namespace,pod) (rate(container_network_receive_bytes_total{'
            f'namespace=~"{namespace_pattern}",pod=~"{pod_pattern}"'
            '}[1m]))'
        ),
        'target_pod_tx_bytes_per_second': (
            'sum by (namespace,pod) (rate(container_network_transmit_bytes_total{'
            f'namespace=~"{namespace_pattern}",pod=~"{pod_pattern}"'
            '}[1m]))'
        ),
        'traefik_cpu_cores': (
            'sum by (pod) (rate(container_cpu_usage_seconds_total{'
            'namespace="kube-system",pod=~"traefik-.*",container!="",image!=""'
            '}[1m]))'
        ),
        'traefik_memory_bytes': (
            'sum by (pod) (container_memory_working_set_bytes{'
            'namespace="kube-system",pod=~"traefik-.*",container!="",image!=""'
            '})'
        ),
        'node_rx_bytes_per_second': (
            'topk(20, rate(node_network_receive_bytes_total{'
            'device!~"lo|cni.*|flannel.*|veth.*|docker.*|br-.*"'
            '}[1m]))'
        ),
        'node_tx_bytes_per_second': (
            'topk(20, rate(node_network_transmit_bytes_total{'
            'device!~"lo|cni.*|flannel.*|veth.*|docker.*|br-.*"'
            '}[1m]))'
        ),
    }

    while not stop_event.is_set() and not global_stop.is_set():
        timestamp = time.time()
        for metric_name, query in queries.items():
            try:
                results = await asyncio.to_thread(prom_query, args.prometheus_url, query)
            except Exception as exc:
                samples.append(
                    {
                        'stage': stage_name,
                        'timestamp': timestamp,
                        'metric': metric_name,
                        'error': str(exc),
                    }
                )
                continue
            for result in results:
                value = float(result.get('value', [0, 0])[1])
                labels = result.get('metric', {})
                samples.append(
                    {
                        'stage': stage_name,
                        'timestamp': timestamp,
                        'metric': metric_name,
                        'labels': labels,
                        'value': value,
                    }
                )
                if metric_name == 'target_pod_cpu_cores' and value > args.max_pod_cpu_cores:
                    print(
                        f'WARN stop threshold cpu pod={labels.get("namespace")}/{labels.get("pod")} '
                        f'value={value:.3f} limit={args.max_pod_cpu_cores:.3f}',
                        flush=True,
                    )
                    global_stop.set()
                if metric_name == 'target_pod_memory_bytes' and value > args.max_pod_memory_bytes:
                    print(
                        f'WARN stop threshold memory pod={labels.get("namespace")}/{labels.get("pod")} '
                        f'value={value:.0f} limit={args.max_pod_memory_bytes:.0f}',
                        flush=True,
                    )
                    global_stop.set()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=args.prometheus_interval_seconds)
        except TimeoutError:
            continue


async def run_stage(
    args: argparse.Namespace,
    *,
    concurrency: int,
    seconds: int,
    assets: dict[str, list[str]],
    samples: list[dict[str, Any]],
    global_stop: asyncio.Event,
) -> StageStats:
    stage_name = f'vu{concurrency}-{seconds}s'
    stats = StageStats(stage_name)
    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(monitor_prometheus(args, stage_name, samples, stop_event, global_stop))
    tasks: list[asyncio.Task[None]] = []
    print(f'STAGE start {stage_name}', flush=True)
    for worker_id in range(concurrency):
        tasks.append(asyncio.create_task(worker(worker_id, args, stats, assets, stop_event)))
        if args.ramp_delay_seconds:
            await asyncio.sleep(args.ramp_delay_seconds)
    try:
        await asyncio.wait_for(global_stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
    finally:
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(monitor_task, return_exceptions=True)
        stats.finished_at = time.time()
    summary = stats.summary()
    print(
        'STAGE summary '
        f'{stage_name} total={summary["total"]} failed={summary["failed"]} '
        f'failure_rate={summary["failure_rate"]:.2%} rps={summary["rps"]:.1f} '
        f'p50={summary["p50_ms"]:.1f}ms p95={summary["p95_ms"]:.1f}ms p99={summary["p99_ms"]:.1f}ms',
        flush=True,
    )
    if summary['failure_rate'] > args.max_failure_rate:
        print(
            f'WARN stop threshold failure_rate={summary["failure_rate"]:.2%} '
            f'limit={args.max_failure_rate:.2%}',
            flush=True,
        )
        global_stop.set()
    if summary['p95_ms'] > args.max_p95_ms:
        print(
            f'WARN stop threshold p95={summary["p95_ms"]:.1f}ms limit={args.max_p95_ms:.1f}ms',
            flush=True,
        )
        global_stop.set()
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Low-disruption app market load test for five published apps.')
    parser.add_argument('--http-host', default='10.120.17.138')
    parser.add_argument('--http-port', type=int, default=8080)
    parser.add_argument('--request-host', default='gpunion.hkust-gz.edu.cn')
    parser.add_argument('--prometheus-url', default='http://127.0.0.1:31755')
    parser.add_argument('--no-prometheus', action='store_true')
    parser.add_argument('--stages', default='5:60')
    parser.add_argument('--think-min-seconds', type=float, default=3.0)
    parser.add_argument('--think-max-seconds', type=float, default=8.0)
    parser.add_argument('--request-timeout', type=float, default=10.0)
    parser.add_argument('--ramp-delay-seconds', type=float, default=0.02)
    parser.add_argument('--prometheus-interval-seconds', type=float, default=5.0)
    parser.add_argument('--static-weight', type=float, default=60.0)
    parser.add_argument('--tex2svg-weight', type=float, default=25.0)
    parser.add_argument('--time-weight', type=float, default=15.0)
    parser.add_argument('--max-assets-per-page', type=int, default=4)
    parser.add_argument('--max-failure-rate', type=float, default=0.01)
    parser.add_argument('--max-p95-ms', type=float, default=3000.0)
    parser.add_argument('--max-pod-cpu-cores', type=float, default=1.6)
    parser.add_argument('--max-pod-memory-bytes', type=float, default=3.2 * 1024 * 1024 * 1024)
    parser.add_argument('--seed', type=int, default=20260601)
    parser.add_argument('--output', default='')
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    random.seed(args.seed)

    stages = parse_stages(args.stages)
    output_path = Path(args.output) if args.output else Path('/tmp/campus-ai-loadtest-results') / (
        f'app-market-5apps-{int(time.time())}.json'
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    global_stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        try:
            loop.add_signal_handler(getattr(signal, signame), global_stop.set)
        except NotImplementedError:
            pass

    assets = discover_assets(args)
    print('ASSETS ' + json.dumps(assets, ensure_ascii=False), flush=True)

    samples: list[dict[str, Any]] = []
    stage_stats: list[StageStats] = []
    for concurrency, seconds in stages:
        if global_stop.is_set():
            break
        stage_stats.append(
            await run_stage(
                args,
                concurrency=concurrency,
                seconds=seconds,
                assets=assets,
                samples=samples,
                global_stop=global_stop,
            )
        )

    result = {
        'started_at': stage_stats[0].started_at if stage_stats else time.time(),
        'finished_at': time.time(),
        'target_apps': TARGET_APPS,
        'args': vars(args),
        'assets': assets,
        'stopped_early': global_stop.is_set(),
        'stages': [item.summary() for item in stage_stats],
        'prometheus_samples': samples,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'OUTPUT {output_path}', flush=True)
    return 2 if global_stop.is_set() else 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == '__main__':
    main()
