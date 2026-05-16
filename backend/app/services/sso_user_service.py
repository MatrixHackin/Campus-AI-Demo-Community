from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SSOUserProfile:
    """从 SSO userinfo 端点同步到本地业务系统的最小用户画像。"""

    sub: str
    username: str
    display_name: str
    user_type: str | None = None
    email: str | None = None
    department: str | None = None
    emp_id: str | None = None


class SSOUserRepository:
    """SSO 用户本地映射仓库。

    这里不保存密码，也不复制 SSO 认证凭据；只保存外部身份 sub 到本地业务用户画像的映射。
    MySQL 不可用或表未初始化时只记录 warning，不阻断 SSO 登录。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _validate_table_name(self) -> str:
        return validate_table_name(self.settings.sso_user_table, 'SSO 用户表名')

    def _connect(self):
        return connect_mysql(self.settings)

    def upsert_login(self, profile: SSOUserProfile) -> int | None:
        if not self.settings.sso_user_persistence_enabled:
            return None
        if not profile.sub:
            logger.warning('SSO 用户落库跳过：缺少 sub')
            return None

        try:
            table_name = self._validate_table_name()
        except ValueError as exc:
            logger.warning('SSO 用户落库跳过：%s', exc)
            return None

        try:
            connection = self._connect()
        except ImportError:
            logger.warning('SSO 用户落库跳过：未安装 PyMySQL')
            return None
        except Exception as exc:
            logger.warning('SSO 用户落库跳过：MySQL 连接失败：%s', exc)
            return None

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (
                      auth_provider,
                      provider_subject,
                      username,
                      display_name,
                      user_type,
                      email,
                      department,
                      emp_id,
                      last_login_at
                    ) VALUES (
                      'sso',
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      CURRENT_TIMESTAMP
                    )
                    ON DUPLICATE KEY UPDATE
                      username = VALUES(username),
                      display_name = VALUES(display_name),
                      user_type = VALUES(user_type),
                      email = VALUES(email),
                      department = VALUES(department),
                      emp_id = VALUES(emp_id),
                      last_login_at = VALUES(last_login_at),
                      id = LAST_INSERT_ID(id)
                    ''',
                    (
                        profile.sub,
                        profile.username,
                        profile.display_name,
                        profile.user_type,
                        profile.email,
                        profile.department,
                        profile.emp_id,
                    ),
                )
                local_user_id = cursor.lastrowid
                return int(local_user_id) if local_user_id else None
        except Exception as exc:
            logger.warning('SSO 用户落库跳过：upsert 失败：%s', exc)
            return None
        finally:
            connection.close()
