from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name


class ContainerUsageLogRepository:
    """log 表访问封装。

    每个 pod_name 维护一条长期汇总记录；删除时标记 deleted，定时任务只更新 running 记录。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _table_name() -> str:
        return validate_table_name('log', '容器日志表名')

    def _connect(self):
        return connect_mysql(self.settings)

    def get_by_pod_name(self, pod_name: str) -> dict | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT *
                    FROM `{table_name}`
                    WHERE pod_name = %s
                    ORDER BY id DESC
                    LIMIT 1
                    ''',
                    (pod_name,),
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def upsert_usage_log(self, values: dict[str, Any]) -> None:
        existing = self.get_by_pod_name(values['pod_name'])
        if existing:
            self._update(existing['id'], values)
        else:
            self._insert(values)

    def _insert(self, values: dict[str, Any]) -> None:
        table_name = self._table_name()
        columns = list(self._write_columns())
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (
                      {', '.join(f'`{column}`' for column in columns)}
                    ) VALUES (
                      {', '.join(['%s'] * len(columns))}
                    )
                    ''',
                    tuple(values.get(column) for column in columns),
                )
        finally:
            connection.close()

    def _update(self, row_id: int, values: dict[str, Any]) -> None:
        table_name = self._table_name()
        columns = list(self._write_columns())
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    UPDATE `{table_name}`
                    SET {', '.join(f'`{column}` = %s' for column in columns)}
                    WHERE id = %s
                    ''',
                    (*tuple(values.get(column) for column in columns), row_id),
                )
        finally:
            connection.close()

    def find_user_profile_by_namespace(self, namespace: str) -> dict[str, str | None]:
        """按 emp_id(namespace) 尽力查找用户邮箱和显示名。"""
        result = {
            'owner_username': None,
            'owner_email': None,
            'user_name': None,
        }
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    '''
                    SELECT username, display_name, email
                    FROM `sso_users`
                    WHERE emp_id = %s
                    ORDER BY last_login_at DESC, id DESC
                    LIMIT 1
                    ''',
                    (namespace,),
                )
                row = cursor.fetchone()
                if row:
                    result['owner_username'] = row.get('username')
                    result['owner_email'] = row.get('email')
                    result['user_name'] = row.get('display_name') or row.get('username')
                    return result

                cursor.execute(
                    '''
                    SELECT username, display_name
                    FROM `users`
                    WHERE emp_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    ''',
                    (namespace,),
                )
                row = cursor.fetchone()
                if row:
                    result['owner_username'] = row.get('username')
                    result['user_name'] = row.get('display_name') or row.get('username')
        finally:
            connection.close()
        return result

    @staticmethod
    def _write_columns() -> tuple[str, ...]:
        return (
            'pod_name',
            'app_name',
            'namespace',
            'gpu_count',
            'start_time',
            'node_name',
            'duration',
            'user_email',
            'user_name',
            'owner_username',
            'owner_email',
            'image',
            'status',
            'deleted_at',
            'cpu_limit_cores',
            'memory_limit_bytes',
            'cpu_core_seconds',
            'cpu_avg_cores',
            'cpu_max_cores',
            'memory_avg_bytes',
            'memory_max_bytes',
            'memory_byte_seconds',
            'memory_gb_hours',
            'network_rx_bytes',
            'network_tx_bytes',
            'metrics_first_collected_at',
            'metrics_last_collected_at',
            'metrics_window_count',
            'metrics_collected_seconds',
            'metrics_complete',
        )


def mysql_datetime(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo:
        return value.replace(tzinfo=None)
    return value
