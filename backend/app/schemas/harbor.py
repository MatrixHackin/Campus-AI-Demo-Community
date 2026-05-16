from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HarborRepository(BaseModel):
    name: str
    full_name: str
    image: str
    artifact_count: int = 0
    pull_count: int = 0
    update_time: str | None = None
    tags: list[str] = Field(default_factory=list)


class HarborProject(BaseModel):
    project_name: str
    exists: bool
    quota: dict[str, Any] = Field(default_factory=dict)
    repos: list[HarborRepository] = Field(default_factory=list)
    error: str | None = None


class HarborMeResponse(BaseModel):
    configured: bool
    registry: str
    public_project: str | None = None
    private_project_name: str | None = None
    private_project: HarborProject | None = None
    public_project_info: HarborProject | None = None
    message: str | None = None
    private_message: str | None = None
    public_message: str | None = None
