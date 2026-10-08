from pydantic import BaseModel, Field


class AgentConfigResponse(BaseModel):
    id: int
    api_base: str
    model_name: str
    has_api_key: bool = False
    api_key_hint: str = ''


class AgentConfigListResponse(BaseModel):
    configs: list[AgentConfigResponse] = Field(default_factory=list)


class AgentConfigCreateRequest(BaseModel):
    api_base: str
    model_name: str
    api_key: str


class AgentConfigUpdateRequest(BaseModel):
    api_base: str
    model_name: str
    api_key: str | None = None


class AgentConfigDeleteResponse(BaseModel):
    ok: bool = True


class AgentChatMessage(BaseModel):
    role: str
    content: str


class AgentChatRequest(BaseModel):
    pod_name: str
    message: str
    config_id: int
    history: list[AgentChatMessage] = Field(default_factory=list)


class AgentChatStep(BaseModel):
    tool: str
    ok: bool = True
    summary: str = ''


class AgentChatResponse(BaseModel):
    reply: str
    steps: list[AgentChatStep] = Field(default_factory=list)


class AgentChatStartResponse(BaseModel):
    run_id: str


class AgentChatRunResponse(BaseModel):
    status: str
    reply: str = ''
    error: str = ''
    steps: list[AgentChatStep] = Field(default_factory=list)
