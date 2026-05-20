from pydantic import BaseModel, Field


class DevboxCreateRequest(BaseModel):
    app_name: str
    connection_password: str
    image: str | None = None
    needs_gpu: bool = False
    gpu_count: int = Field(default=0, ge=0, le=2)
    cpu_cores: int | None = Field(default=None, ge=1)
    memory_gb: int | None = Field(default=None, ge=1)
    shm_gb: int | None = Field(default=None, ge=1)


class DevboxCreateResponse(BaseModel):
    pod_name: str
    namespace: str
    app_name: str
    url: str
    ssh_username: str | None = None
    webssh_url: str | None = None
    native_ssh_command: str | None = None
    is_published: bool = False
    image: str
    cpu: str
    memory: str
    gpu_count: int = 0
    shm: str | None = None
    status: str
    created_at: str


class ContainerItem(BaseModel):
    name: str
    image: str
    status: str
    node_name: str | None = None
    start_time: str | None = None
    duration: int = 0
    app_name: str | None = None
    url: str | None = None
    ssh_username: str | None = None
    webssh_url: str | None = None
    native_ssh_command: str | None = None
    is_published: bool = False


class ContainerListResponse(BaseModel):
    namespace: str
    containers: list[ContainerItem]


class ContainerDeleteResponse(BaseModel):
    pod_name: str
    namespace: str
    app_name: str | None = None
    status: str


class ContainerCommitRequest(BaseModel):
    image_name: str


class ContainerCommitResponse(BaseModel):
    job_name: str
    pod_name: str
    namespace: str
    image: str
    status: str = 'Running'
    message: str


class K3SJobStatusResponse(BaseModel):
    job_name: str
    status: str
    message: str
    image: str | None = None


class ContainerCurrentUsage(BaseModel):
    cpu_cores: float = 0
    cpu_max_cores: float = 0
    memory_bytes: int = 0
    memory_max_bytes: int = 0
    network_rx_bps: float = 0
    network_tx_bps: float = 0


class ContainerTotalUsage(BaseModel):
    cpu_core_seconds: float = 0
    memory_gb_hours: float = 0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    metrics_last_collected_at: str | None = None
    metrics_complete: bool = True


class MyAppUsageItem(BaseModel):
    pod_name: str
    app_name: str | None = None
    status: str
    node_name: str | None = None
    image: str | None = None
    start_time: str | None = None
    duration: int = 0
    cpu_limit_cores: float | None = None
    memory_limit_bytes: int | None = None
    current: ContainerCurrentUsage
    total: ContainerTotalUsage


class MyAppsUsageResponse(BaseModel):
    namespace: str
    apps: list[MyAppUsageItem]


class UsageTrendPoint(BaseModel):
    timestamp: float
    value: float


class UsageTrendSeries(BaseModel):
    key: str
    label: str
    unit: str
    current_value: float = 0
    points: list[UsageTrendPoint]


class ContainerUsageTrendResponse(BaseModel):
    pod_name: str
    app_name: str | None = None
    status: str
    window_seconds: int
    step_seconds: int
    complete: bool = True
    series: list[UsageTrendSeries]


class AppNameAvailabilityResponse(BaseModel):
    app_name: str
    available: bool
    url: str
    message: str | None = None
