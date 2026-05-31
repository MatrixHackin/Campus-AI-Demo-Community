from pydantic import BaseModel, Field


class AppReviewItem(BaseModel):
    id: int | None = None
    username: str | None = None
    display_name: str | None = None
    rating: int = Field(..., ge=0, le=5)
    comment: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AppReviewSummary(BaseModel):
    rating_avg: float = 0
    rating_sum: int = 0
    review_count: int = 0


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
    rating_avg: float = 0
    rating_sum: int = 0
    review_count: int = 0
    is_published: bool = False
    review_status: str = 'approved'
    submitted_at: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    reject_reason: str | None = None
    responsibility_ack: bool = False
    responsibility_ack_version: str | None = None
    responsibility_ack_at: str | None = None
    my_review: AppReviewItem | None = None
    published_at: str | None = None
    updated_at: str | None = None


class PublishedAppListResponse(BaseModel):
    apps: list[PublishedAppItem]


class AppReviewRequest(BaseModel):
    rating: int = Field(..., ge=0, le=5)
    comment: str | None = Field(default=None, max_length=240)


class AppReviewListResponse(BaseModel):
    summary: AppReviewSummary
    my_review: AppReviewItem | None = None
    reviews: list[AppReviewItem]
    next_offset: int | None = None
    has_more: bool = False
    sort: str = 'desc'


class PublicationReviewSettings(BaseModel):
    review_policy: str
    responsibility_ack_version: str


class PublicationReviewSettingsUpdate(BaseModel):
    review_policy: str
    responsibility_ack_version: str | None = Field(default=None, max_length=32)


class PublicationStatusItem(BaseModel):
    pod_name: str
    is_published: bool = False
    review_status: str = 'unpublished'
    submitted_at: str | None = None
    reviewed_at: str | None = None


class PublicationStatusListResponse(BaseModel):
    statuses: list[PublicationStatusItem]


class PublicationReviewListResponse(BaseModel):
    apps: list[PublishedAppItem]


class PublicationReviewActionRequest(BaseModel):
    review_note: str | None = Field(default=None, max_length=500)
    reject_reason: str | None = Field(default=None, max_length=500)
