from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_auth_service, get_sso_service, get_token_store, settings
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.auth_service import AuthService
from app.services.sso_service import SSOService, generate_code_challenge, generate_code_verifier
from app.services.token_store import TokenStore

router = APIRouter(prefix='/auth', tags=['auth'])
callback_router = APIRouter(tags=['sso'])


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.token_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path='/',
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path='/',
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


@router.post('/login', response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
):
    result = await auth_service.login(payload.username, payload.password)
    set_session_cookie(response, result['access_token'])
    return result


@router.get('/me')
async def me(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    token_store: TokenStore = Depends(get_token_store),
):
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='未登录')
    session = token_store.get_session(session_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效')
    return {
        'user': {
            'id': session.user_id,
            'username': session.username,
            'display_name': session.display_name,
        },
        'auth_provider': session.auth_provider,
        'expires_at': session.expires_at.isoformat(),
    }


@router.get('/sso/login')
async def sso_login(
    token_store: TokenStore = Depends(get_token_store),
    sso_service: SSOService = Depends(get_sso_service),
):
    if not settings.sso_client_id or not settings.sso_client_secret:
        raise HTTPException(status_code=500, detail='SSO 未配置')

    code_verifier = generate_code_verifier()
    state = token_store.issue_oauth_state(code_verifier)
    authorize_url = sso_service.build_authorize_url(
        state=state,
        code_challenge=generate_code_challenge(code_verifier),
    )
    return RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)


@router.api_route('/logout', methods=['GET', 'POST'])
async def logout(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    token_store: TokenStore = Depends(get_token_store),
    sso_service: SSOService = Depends(get_sso_service),
):
    id_token = None
    if session_token:
        session = token_store.get_session(session_token)
        if session:
            id_token = session.id_token
        token_store.revoke_session(session_token)

    if id_token:
        response = RedirectResponse(sso_service.build_logout_url(id_token), status_code=status.HTTP_302_FOUND)
    else:
        response = RedirectResponse('/login', status_code=status.HTTP_302_FOUND)
    clear_session_cookie(response)
    return response


@callback_router.get('/signin-oidc')
async def signin_oidc(
    code: str | None = None,
    state: str | None = None,
    token_store: TokenStore = Depends(get_token_store),
    sso_service: SSOService = Depends(get_sso_service),
):
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='登录失败，请重新登录')
    if not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='登录状态无效，请重新登录')

    oauth_state = token_store.consume_oauth_state(state)
    if not oauth_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='登录状态无效，请重新登录')

    token_response = sso_service.exchange_code_for_token(code=code, code_verifier=oauth_state.code_verifier)
    access_token = token_response.get('access_token')
    id_token = token_response.get('id_token')
    if not access_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='登录失败，请重新登录')

    userinfo = sso_service.get_userinfo(access_token)
    sub = userinfo.get('sub')
    if not sub:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='登录失败，请重新登录')

    username = userinfo.get('name') or sub
    display_name = userinfo.get('display_name') or username
    local_session = token_store.issue_token(
        user_id=f'sso:{sub}',
        username=username,
        display_name=display_name,
        auth_provider='sso',
        id_token=id_token,
        access_token=access_token,
    )

    response = RedirectResponse('/dashboard', status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, local_session.token)
    return response


@callback_router.get('/signout-callback')
async def signout_callback():
    response = RedirectResponse('/login', status_code=status.HTTP_302_FOUND)
    clear_session_cookie(response)
    return response
