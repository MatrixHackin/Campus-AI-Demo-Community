from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/login', response_model=LoginResponse)
async def login(payload: LoginRequest, auth_service: AuthService = Depends(get_auth_service)):
    return await auth_service.login(payload.username, payload.password)
