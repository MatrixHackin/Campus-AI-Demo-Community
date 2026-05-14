from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import get_sandbox_service, get_token_store
from app.schemas.sandbox import SandboxCreateRequest, SandboxListResponse, SandboxResponse
from app.services.sandbox_service import SandboxService
from app.services.token_store import SessionRecord, TokenStore

router = APIRouter(prefix='/sandboxes', tags=['sandboxes'])
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token_store: TokenStore = Depends(get_token_store),
) -> SessionRecord:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='缺少登录凭证')

    session = token_store.get_session(credentials.credentials)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效，请重新登录')
    return session


@router.post('', response_model=SandboxResponse)
def create_sandbox(
    payload: SandboxCreateRequest,
    sandbox_service: SandboxService = Depends(get_sandbox_service),
    current_user: SessionRecord = Depends(get_current_user),
):
    return sandbox_service.create_sandbox(current_user.username, payload)


@router.get('/me', response_model=SandboxListResponse)
def list_my_sandboxes(
    sandbox_service: SandboxService = Depends(get_sandbox_service),
    current_user: SessionRecord = Depends(get_current_user),
):
    return {'items': sandbox_service.list_sandboxes(current_user.username)}
