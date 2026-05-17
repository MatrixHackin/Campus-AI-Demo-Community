from pydantic import BaseModel


class DevboxCreateRequest(BaseModel):
    app_name: str
    connection_password: str


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
    status: str
    created_at: str


class ContainerItem(BaseModel):
    name: str
    image: str
    status: str
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


class AppNameAvailabilityResponse(BaseModel):
    app_name: str
    available: bool
    url: str
    message: str | None = None
