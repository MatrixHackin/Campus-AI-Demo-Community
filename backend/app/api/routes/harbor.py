from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_harbor_service, get_token_store, settings
from app.schemas.harbor import HarborMeResponse
from app.services.harbor_service import HarborService
from app.services.token_store import SessionRecord, TokenStore

router = APIRouter(prefix='/harbor', tags=['harbor'])


def get_current_session(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    token_store: TokenStore = Depends(get_token_store),
) -> SessionRecord:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='缺少登录凭证')

    session = token_store.get_session(session_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效，请重新登录')
    return session


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
