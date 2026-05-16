from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_k3s_service, get_token_store, settings
from app.schemas.k3s import ContainerListResponse, DevboxCreateResponse
from app.services.k3s_service import K3SService
from app.services.token_store import SessionRecord, TokenStore

router = APIRouter(prefix='/k3s', tags=['k3s'])


def get_current_session(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    token_store: TokenStore = Depends(get_token_store),
) -> SessionRecord:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='缺少登录凭证')

    session = token_store.get_session(session_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效，请重新登录')
    if not session.emp_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='当前用户缺少 emp_id，无法访问容器')
    return session


@router.post('/devbox', response_model=DevboxCreateResponse)
async def create_devbox_container(
    current_session: SessionRecord = Depends(get_current_session),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.create_devbox_container, current_session.emp_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/containers', response_model=ContainerListResponse)
async def list_user_containers(
    current_session: SessionRecord = Depends(get_current_session),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.list_user_containers, current_session.emp_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
