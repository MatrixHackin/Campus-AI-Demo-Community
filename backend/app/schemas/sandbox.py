from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SandboxCreateRequest(BaseModel):
    image: Optional[str] = Field(default=None, description='容器镜像')
    command: Optional[List[str]] = Field(default=None, description='容器启动命令')
    args: Optional[List[str]] = Field(default=None, description='容器启动参数')
    env: Dict[str, str] = Field(default_factory=dict, description='容器环境变量')
    cpu_request: str = Field(default='250m')
    memory_request: str = Field(default='512Mi')


class SandboxResponse(BaseModel):
    sandbox_id: str
    pod_name: str
    namespace: str
    status: str
    image: str
    created_at: datetime
    access_hint: str
    owner: str


class SandboxListResponse(BaseModel):
    items: List[SandboxResponse]
