from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_session, get_harbor_service
from app.schemas.harbor import HarborMeResponse
from app.services.harbor_service import HarborService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/harbor', tags=['harbor'])


@router.get('/me', response_model=HarborMeResponse)
async def get_my_harbor_images(
    include_tags: bool = Query(default=False),
    current_session: SessionRecord = Depends(get_current_session),
    harbor_service: HarborService = Depends(get_harbor_service),
):
    return await run_in_threadpool(
        harbor_service.get_user_projects,
        current_session.email,
        include_tags,
    )
