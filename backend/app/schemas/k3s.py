from pydantic import BaseModel


class DevboxCreateRequest(BaseModel):
    app_name: str
    connection_password: str


class DevboxCreateResponse(BaseModel):
    pod_name: str
    namespace: str
    app_name: str
    url: str
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
