from fastapi import Cookie, Depends, HTTPException, status

from app.core.config import get_settings
from app.services.auth_service import AuthService
from app.services.harbor_service import HarborService
from app.services.k3s_service import K3SService
from app.services.publication_service import PublicationService
from app.services.ssh_gateway_service import SSHGatewayService
from app.services.sso_service import SSOService
from app.services.sso_user_service import SSOUserRepository
from app.services.token_store import SessionRecord, TokenStore

settings = get_settings()
token_store = TokenStore(ttl_hours=settings.token_ttl_hours)
auth_service = AuthService(settings=settings, token_store=token_store)
harbor_service = HarborService(settings=settings)
k3s_service = K3SService(settings=settings)
ssh_gateway_service = SSHGatewayService(settings=settings, k3s_service=k3s_service)
publication_service = PublicationService(settings=settings)
sso_service = SSOService(settings=settings)
sso_user_repository = SSOUserRepository(settings=settings)


def get_token_store() -> TokenStore:
    return token_store


def get_auth_service() -> AuthService:
    return auth_service


def get_harbor_service() -> HarborService:
    return harbor_service


def get_k3s_service() -> K3SService:
    return k3s_service


def get_ssh_gateway_service() -> SSHGatewayService:
    return ssh_gateway_service


def get_publication_service() -> PublicationService:
    return publication_service


def get_sso_service() -> SSOService:
    return sso_service


def get_sso_user_repository() -> SSOUserRepository:
    return sso_user_repository


def get_current_session(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    store: TokenStore = Depends(get_token_store),
) -> SessionRecord:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='缺少登录凭证')

    session = store.get_session(session_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录状态已失效，请重新登录')
    return session


def get_current_session_with_emp_id(
    session: SessionRecord = Depends(get_current_session),
) -> SessionRecord:
    if not session.emp_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='当前用户缺少 emp_id，无法访问容器')
    return session
