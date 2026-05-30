import hmac

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_k3s_service, get_token_store, settings

router = APIRouter(prefix='/internal', tags=['internal'])


class SSHResolveRequest(BaseModel):
    app_name: str
    ssh_username: str
    password: str | None = None
    session_token: str | None = None


class SSHResolveResponse(BaseModel):
    app_name: str
    namespace: str
    pod_name: str | None = None
    ssh_username: str
    password: str
    service_name: str
    host: str
    port: int = 22


def _require_internal_token(header_token: str | None) -> None:
    expected = settings.internal_api_token.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='内部接口令牌未配置',
        )
    if not header_token or not hmac.compare_digest(header_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='内部接口令牌无效')


@router.post('/ssh/resolve', response_model=SSHResolveResponse)
def resolve_ssh_target(
    payload: SSHResolveRequest,
    internal_token: str | None = Header(default=None, alias='X-Campus-AI-Internal-Token'),
):
    _require_internal_token(internal_token)

    owner_username = None
    if payload.session_token:
        session = get_token_store().get_session(payload.session_token)
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效')
        owner_username = session.username

    if not payload.password and not owner_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='缺少 SSH 密码或会话凭证')

    try:
        return get_k3s_service().get_ssh_target(
            app_name=payload.app_name,
            ssh_username=payload.ssh_username,
            owner_username=owner_username,
            password=payload.password,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
