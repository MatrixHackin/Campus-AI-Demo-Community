from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class LoginUser(BaseModel):
    id: str
    username: str
    display_name: str
    local_user_id: int | None = None
    type: str | None = None
    email: str | None = None
    department: str | None = None
    emp_id: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: str
    auth_provider: str = 'local'
    user: LoginUser
