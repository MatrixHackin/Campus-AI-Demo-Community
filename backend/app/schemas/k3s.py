from pydantic import BaseModel


class DevboxCreateResponse(BaseModel):
    pod_name: str
    namespace: str
    image: str
    cpu: str
    memory: str
    status: str
    created_at: str


class ContainerItem(BaseModel):
    name: str
    image: str
    status: str


class ContainerListResponse(BaseModel):
    namespace: str
    containers: list[ContainerItem]
