from app.core.config import get_settings
from app.services.auth_service import AuthService
from app.services.sso_service import SSOService
from app.services.sso_user_service import SSOUserRepository
from app.services.token_store import TokenStore

settings = get_settings()
token_store = TokenStore(ttl_hours=settings.token_ttl_hours)
auth_service = AuthService(settings=settings, token_store=token_store)
sso_service = SSOService(settings=settings)
sso_user_repository = SSOUserRepository(settings=settings)


def get_token_store() -> TokenStore:
    return token_store


def get_auth_service() -> AuthService:
    return auth_service


def get_sso_service() -> SSOService:
    return sso_service


def get_sso_user_repository() -> SSOUserRepository:
    return sso_user_repository
