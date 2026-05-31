import hmac

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from app.api.deps import get_k3s_service, get_token_store, settings
from app.services.app_page_renderer import render_unavailable_app_page

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


def _require_internal_token(header_token: str | None, query_token: str | None = None) -> None:
    expected = settings.internal_api_token.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='内部接口令牌未配置',
        )
    provided = header_token or query_token
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='内部接口令牌无效')


@router.get('/app-access/authorize', include_in_schema=False)
def authorize_app_access(
    request: Request,
    token: str | None = Query(default=None),
    internal_token: str | None = Header(default=None, alias='X-Campus-AI-Internal-Token'),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    _require_internal_token(internal_token, token)

    session = get_token_store().get_session(session_token) if session_token else None
    request_uri = request.headers.get('x-forwarded-uri') or request.headers.get('x-original-uri')
    try:
        result = get_k3s_service().authorize_app_http_access(request_uri=request_uri, session=session)
    except RuntimeError:
        content = render_unavailable_app_page(
            title='应用暂不可访问',
            message='访问状态校验失败，请稍后重试。',
            home_url='/community',
        )
        return HTMLResponse(content=content, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if result.get('allowed'):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    content = render_unavailable_app_page(
        title=result.get('title') or '应用已下架',
        message=result.get('message') or '该应用当前不可访问。',
        app_name=result.get('app_name'),
        home_url='/community',
    )
    return HTMLResponse(content=content, status_code=int(result.get('status_code') or status.HTTP_410_GONE))


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
