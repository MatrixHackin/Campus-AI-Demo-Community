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
