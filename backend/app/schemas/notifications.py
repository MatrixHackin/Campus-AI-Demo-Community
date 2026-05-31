from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    id: int
    title: str
    content: str
    type: str
    scope: str
    recipient_username: str | None = None
    sender_username: str | None = None
    related_type: str | None = None
    related_id: int | None = None
    read_at: str | None = None
    dismissed_at: str | None = None
    expires_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NotificationListResponse(BaseModel):
    notifications: list[NotificationItem]
    unread_count: int = 0


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int = 0


class NotificationActionResponse(BaseModel):
    ok: bool = True
    unread_count: int = 0


class AdminNotificationCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=2000)
    type: str = Field(default='system_announcement', max_length=64)
    scope: str = Field(default='all', max_length=16)
    recipient_username: str | None = Field(default=None, max_length=255)
    related_type: str | None = Field(default=None, max_length=64)
    related_id: int | None = Field(default=None, ge=1)
    expires_at: str | None = None


class AdminNotificationListResponse(BaseModel):
    notifications: list[NotificationItem]


class AdminNotificationDeleteResponse(BaseModel):
    ok: bool = True
