from __future__ import annotations

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name


class PlatformSettingsRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _table_name() -> str:
        return validate_table_name('platform_settings', '平台设置表名')

    def _connect(self):
        return connect_mysql(self.settings)

    def get_value(self, key: str, default: str | None = None) -> str | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT setting_value
                    FROM `{table_name}`
                    WHERE setting_key = %s
                    LIMIT 1
                    ''',
                    (key,),
                )
                row = cursor.fetchone()
                return row['setting_value'] if row else default
        finally:
            connection.close()

    def set_value(self, key: str, value: str, updated_by: str | None = None) -> None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (
                      setting_key,
                      setting_value,
                      updated_by
                    ) VALUES (
                      %s,
                      %s,
                      %s
                    )
                    ON DUPLICATE KEY UPDATE
                      setting_value = VALUES(setting_value),
                      updated_by = VALUES(updated_by),
                      updated_at = CURRENT_TIMESTAMP
                    ''',
                    (key, value, updated_by),
                )
        finally:
            connection.close()
