from pydantic import BaseModel


class PublishedAppItem(BaseModel):
    id: int
    pod_name: str
    app_name: str
    app_description: str | None = None
    cover_url: str | None = None
    app_url: str
    owner_username: str
    owner_display_name: str | None = None
    visit_count: int = 0
    like_count: int = 0
    is_liked: bool = False
    published_at: str | None = None
    updated_at: str | None = None


class PublishedAppListResponse(BaseModel):
    apps: list[PublishedAppItem]
