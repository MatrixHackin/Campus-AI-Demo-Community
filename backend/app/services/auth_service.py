from __future__ import annotations

import hashlib

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.db.interfaces import AuthRepository, UserRecord
from app.db.mysql import connect_mysql, validate_table_name
from app.services.token_store import TokenStore


class DemoAuthRepository(AuthRepository):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        if username == self.settings.demo_username and password == self.settings.demo_password:
            return UserRecord(
                user_id='demo-user-001',
                username=username,
                display_name=self.settings.demo_display_name,
                emp_id=self.settings.demo_emp_id,
            )
        return None


class PendingDatabaseAuthRepository(AuthRepository):
    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail='请实现 app/db/interfaces.py 中的认证接口后再启用 custom 模式。',
        )


class MySQLAuthRepository(AuthRepository):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _validate_table_name(self) -> str:
        try:
            return validate_table_name(self.settings.sso_user_table, '统一用户表名')
        except ValueError as exc:
            raise HTTPException(status_code=500, detail='用户表名配置不合法') from exc

    def _validate_legacy_table_name(self) -> str:
        try:
            return validate_table_name(self.settings.mysql_user_table, '旧用户表名')
        except ValueError as exc:
            raise HTTPException(status_code=500, detail='旧用户表名配置不合法') from exc

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        """校验格式：pbkdf2_sha256$iterations$salt$hash。"""
        try:
            algorithm, iterations, salt, expected_hash = stored_hash.split('$', 3)
        except ValueError:
            return False

        if algorithm != 'pbkdf2_sha256' or not salt or not expected_hash or not iterations:
            return False

        actual_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            int(iterations),
        ).hex()
        return actual_hash == expected_hash

    def _authenticate_sync(self, username: str, password: str) -> UserRecord | None:
        table_name = self._validate_table_name()
        login_username = username.strip().lower()

        try:
            connection = connect_mysql(self.settings)
        except ImportError as exc:
            raise HTTPException(status_code=500, detail='未安装 PyMySQL，请先安装 MySQL 驱动') from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'MySQL 连接失败: {str(exc)}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      id,
                      username,
                      display_name,
                      user_type,
                      email,
                      department,
                      emp_id,
                      password_hash
                    FROM `{table_name}`
                    WHERE auth_provider = 'local'
                      AND username = %s
                      AND local_login_enabled = 1
                      AND password_hash IS NOT NULL
                    LIMIT 1
                    ''',
                    (login_username,),
                )
                row = cursor.fetchone()
                if not row:
                    legacy_table_name = self._validate_legacy_table_name()
                    if legacy_table_name != table_name:
                        cursor.execute(
                            f'''
                            SELECT id, username, display_name, emp_id, password_hash
                            FROM `{legacy_table_name}`
                            WHERE username = %s
                            LIMIT 1
                            ''',
                            (username,),
                        )
                        legacy_row = cursor.fetchone()
                        if legacy_row:
                            legacy_row['_legacy_user'] = True
                            row = legacy_row
        finally:
            connection.close()

        if not row:
            return None

        if not self._verify_password(
            password=password,
            stored_hash=row.get('password_hash') or '',
        ):
            return None

        is_legacy_user = bool(row.get('_legacy_user'))
        return UserRecord(
            user_id=f'legacy:{row["id"]}' if is_legacy_user else f'local:{row["id"]}',
            username=row['username'],
            display_name=row.get('display_name') or row['username'],
            local_user_id=None if is_legacy_user else int(row['id']),
            auth_provider='local',
            user_type=row.get('user_type'),
            email=row.get('email'),
            department=row.get('department'),
            emp_id=row.get('emp_id'),
        )

    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        return await run_in_threadpool(self._authenticate_sync, username, password)


class AuthService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.token_store = token_store
        self.repository = self._build_repository()

    def _build_repository(self) -> AuthRepository:
        if self.settings.auth_backend == 'mysql':
            return MySQLAuthRepository(self.settings)
        if self.settings.auth_backend == 'custom':
            return PendingDatabaseAuthRepository()
        return DemoAuthRepository(self.settings)

    async def login(self, username: str, password: str) -> dict:
        user = await self.repository.authenticate(username, password)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='账号或密码错误')

        session = self.token_store.issue_token(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            local_user_id=user.local_user_id,
            auth_provider=user.auth_provider,
            user_type=user.user_type,
            email=user.email,
            department=user.department,
            emp_id=user.emp_id,
        )
        return {
            'access_token': session.token,
            'token_type': 'bearer',
            'expires_at': session.expires_at.isoformat(),
            'auth_provider': session.auth_provider,
            'user': {
                'id': user.user_id,
                'username': user.username,
                'display_name': user.display_name,
                'local_user_id': session.local_user_id,
                'type': user.user_type,
                'email': user.email,
                'department': user.department,
                'emp_id': user.emp_id,
            },
        }
