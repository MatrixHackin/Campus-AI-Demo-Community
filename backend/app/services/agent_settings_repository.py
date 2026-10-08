from __future__ import annotations

import logging

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS `{table}` (
  id BIGINT NOT NULL AUTO_INCREMENT,
  username VARCHAR(255) NOT NULL,
  api_base VARCHAR(512) NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  api_key VARCHAR(1024) NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_agent_settings_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
'''


class AgentSettingsRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ready = False

    @staticmethod
    def _table_name() -> str:
        return validate_table_name('user_agent_settings', 'Agent 配置表名')

    def _connect(self):
        return connect_mysql(self.settings)

    def ensure_table(self) -> None:
        if self._ready:
            return
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_CREATE_TABLE_SQL.format(table=table_name))
                cursor.execute(f'SHOW COLUMNS FROM `{table_name}`')
                columns = {row['Field'] for row in cursor.fetchall()}
                if 'id' not in columns:
                    cursor.execute(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")
                    if cursor.fetchall():
                        cursor.execute(f'ALTER TABLE `{table_name}` DROP PRIMARY KEY')
                    cursor.execute(
                        f'ALTER TABLE `{table_name}` '
                        'ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST'
                    )
                cursor.execute(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'idx_agent_settings_username'")
                if not cursor.fetchall():
                    cursor.execute(
                        f'ALTER TABLE `{table_name}` ADD KEY idx_agent_settings_username (username)'
                    )
            self._ready = True
        except Exception as exc:
            raise RuntimeError(f'准备开发 Agent 配置表失败：{exc}') from exc
        finally:
            connection.close()

    def list(self, username: str) -> list[dict]:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT id, username, api_base, model_name, api_key, updated_at
                    FROM `{table_name}`
                    WHERE username = %s
                    ORDER BY updated_at DESC, id DESC
                    ''',
                    (username,),
                )
                return list(cursor.fetchall())
        except Exception as exc:
            raise RuntimeError(f'读取开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()

    def count(self, username: str) -> int:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) AS total FROM `{table_name}` WHERE username = %s',
                    (username,),
                )
                row = cursor.fetchone() or {}
                return int(row.get('total') or 0)
        except Exception as exc:
            raise RuntimeError(f'读取开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()

    def get_owned(self, username: str, config_id: int) -> dict | None:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT id, username, api_base, model_name, api_key, updated_at
                    FROM `{table_name}`
                    WHERE id = %s AND username = %s
                    LIMIT 1
                    ''',
                    (config_id, username),
                )
                return cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(f'读取开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()

    def create(self, *, username: str, api_base: str, model_name: str, api_key: str) -> dict:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (username, api_base, model_name, api_key)
                    VALUES (%s, %s, %s, %s)
                    ''',
                    (username, api_base, model_name, api_key),
                )
                new_id = int(cursor.lastrowid)
        except Exception as exc:
            raise RuntimeError(f'保存开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()
        saved = self.get_owned(username, new_id)
        if not saved:
            raise RuntimeError('保存开发 Agent 配置失败')
        return saved

    def update(
        self,
        *,
        username: str,
        config_id: int,
        api_base: str,
        model_name: str,
        api_key: str | None,
    ) -> dict | None:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if api_key is None:
                    cursor.execute(
                        f'''
                        UPDATE `{table_name}`
                        SET api_base = %s, model_name = %s
                        WHERE id = %s AND username = %s
                        ''',
                        (api_base, model_name, config_id, username),
                    )
                else:
                    cursor.execute(
                        f'''
                        UPDATE `{table_name}`
                        SET api_base = %s, model_name = %s, api_key = %s
                        WHERE id = %s AND username = %s
                        ''',
                        (api_base, model_name, api_key, config_id, username),
                    )
                if cursor.rowcount == 0 and not self.get_owned(username, config_id):
                    return None
        except Exception as exc:
            raise RuntimeError(f'保存开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()
        return self.get_owned(username, config_id)

    def delete(self, username: str, config_id: int) -> bool:
        self.ensure_table()
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM `{table_name}` WHERE id = %s AND username = %s',
                    (config_id, username),
                )
                return cursor.rowcount > 0
        except Exception as exc:
            raise RuntimeError(f'删除开发 Agent 配置失败：{exc}') from exc
        finally:
            connection.close()
