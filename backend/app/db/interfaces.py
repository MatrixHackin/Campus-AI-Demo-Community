from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class UserRecord:
    user_id: str
    username: str
    display_name: str
    local_user_id: int | None = None
    auth_provider: str = 'local'
    user_type: str | None = None
    email: str | None = None
    department: str | None = None
    emp_id: str | None = None


class AuthRepository(ABC):
    """数据库认证接口。

    你可以在这里接入 MySQL / PostgreSQL / Redis / LDAP 等认证逻辑，
    然后在 `app/services/auth_service.py` 中替换默认仓库。
    """

    @abstractmethod
    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        raise NotImplementedError
