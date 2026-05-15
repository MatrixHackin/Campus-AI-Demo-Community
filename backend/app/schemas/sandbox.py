from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SandboxCreateRequest(BaseModel):
    image: Optional[str] = Field(default=None, description='容器镜像')
    command: Optional[List[str]] = Field(default=None, description='容器启动命令')
    args: Optional[List[str]] = Field(default=None, description='容器启动参数')
    env: Dict[str, str] = Field(default_factory=dict, description='容器环境变量')
    cpu_request: Optional[str] = Field(default=None, description='CPU request/limit，例如 4 或 250m')
    memory_request: Optional[str] = Field(default=None, description='Memory request/limit，例如 8Gi 或 512Mi')
    gpu_count: int = Field(default=0, ge=0, description='申请 GPU/NPU 数量；0 表示不申请')
    sandbox_username: Optional[str] = Field(default=None, description='容器内默认用户名')
    sandbox_password: Optional[str] = Field(default=None, description='容器内默认密码')
    pod_label: Optional[str] = Field(default=None, description='额外业务标签')
    enable_nodeport: Optional[bool] = Field(default=None, description='是否为 SSH 端口创建 NodePort Service')
    wait_until_running: Optional[bool] = Field(default=None, description='是否等待 Pod 到 Running/Succeeded 后返回')


class SandboxResponse(BaseModel):
    sandbox_id: str
    pod_name: str
    namespace: str
    status: str
    image: str
    created_at: datetime
    access_hint: str
    owner: str
    services: List[Dict[str, Any]] = Field(default_factory=list)


class SandboxListResponse(BaseModel):
    items: List[SandboxResponse]
