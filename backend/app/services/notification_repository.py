from __future__ import annotations

from datetime import datetime

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name


class NotificationRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _notifications_table_name() -> str:
        return validate_table_name('platform_notifications', '通知表名')

    @staticmethod
    def _receipts_table_name() -> str:
        return validate_table_name('platform_notification_receipts', '通知回执表名')

    def _connect(self):
        return connect_mysql(self.settings)

    @staticmethod
    def _select_columns() -> str:
        return '''
          n.id,
          n.title,
          n.content,
          n.notification_type,
          n.scope,
          n.recipient_username,
          n.sender_username,
          n.related_type,
          n.related_id,
          n.expires_at,
          n.is_deleted,
          n.created_at,
          n.updated_at
        '''

    def create_notification(
        self,
        *,
        title: str,
        content: str,
        notification_type: str,
        scope: str,
        sender_username: str | None,
        recipient_username: str | None = None,
        related_type: str | None = None,
        related_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        notifications_table = self._notifications_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{notifications_table}` (
                      title,
                      content,
                      notification_type,
                      scope,
                      recipient_username,
                      sender_username,
                      related_type,
                      related_id,
                      expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (
                        title,
                        content,
                        notification_type,
                        scope,
                        recipient_username,
                        sender_username,
                        related_type,
                        related_id,
                        expires_at,
                    ),
                )
                notification_id = cursor.lastrowid
        finally:
            connection.close()
        row = self.get_by_id(notification_id)
        if not row:
            raise RuntimeError('创建通知后读取失败')
        return row

    def get_by_id(self, notification_id: int) -> dict | None:
        notifications_table = self._notifications_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      {self._select_columns()},
                      NULL AS read_at,
                      NULL AS dismissed_at
                    FROM `{notifications_table}` n
                    WHERE n.id = %s
                    LIMIT 1
                    ''',
                    (notification_id,),
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def list_admin_notifications(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        notifications_table = self._notifications_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      {self._select_columns()},
                      NULL AS read_at,
                      NULL AS dismissed_at
                    FROM `{notifications_table}` n
                    WHERE n.is_deleted = 0
                    ORDER BY n.created_at DESC, n.id DESC
                    LIMIT %s OFFSET %s
                    ''',
                    (limit, offset),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def list_user_notifications(
        self,
        *,
        username: str,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        notifications_table = self._notifications_table_name()
        receipts_table = self._receipts_table_name()
        unread_clause = 'AND r.read_at IS NULL' if unread_only else ''
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      {self._select_columns()},
                      r.read_at,
                      r.dismissed_at
                    FROM `{notifications_table}` n
                    LEFT JOIN `{receipts_table}` r
                      ON r.notification_id = n.id
                     AND r.recipient_username = %s
                    WHERE n.is_deleted = 0
                      AND (n.expires_at IS NULL OR n.expires_at > CURRENT_TIMESTAMP)
                      AND (
                        n.scope = 'all'
                        OR (n.scope = 'user' AND n.recipient_username = %s)
                      )
                      AND r.dismissed_at IS NULL
                      {unread_clause}
                    ORDER BY n.created_at DESC, n.id DESC
                    LIMIT %s OFFSET %s
                    ''',
                    (username, username, limit, offset),
                )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def count_unread(self, *, username: str) -> int:
        notifications_table = self._notifications_table_name()
        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT COUNT(*) AS unread_count
                    FROM `{notifications_table}` n
                    LEFT JOIN `{receipts_table}` r
                      ON r.notification_id = n.id
                     AND r.recipient_username = %s
                    WHERE n.is_deleted = 0
                      AND (n.expires_at IS NULL OR n.expires_at > CURRENT_TIMESTAMP)
                      AND (
                        n.scope = 'all'
                        OR (n.scope = 'user' AND n.recipient_username = %s)
                      )
                      AND r.read_at IS NULL
                      AND r.dismissed_at IS NULL
                    ''',
                    (username, username),
                )
                row = cursor.fetchone() or {}
                return int(row.get('unread_count') or 0)
        finally:
            connection.close()

    def visible_notification_exists(self, *, username: str, notification_id: int) -> bool:
        notifications_table = self._notifications_table_name()
        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT n.id
                    FROM `{notifications_table}` n
                    LEFT JOIN `{receipts_table}` r
                      ON r.notification_id = n.id
                     AND r.recipient_username = %s
                    WHERE n.id = %s
                      AND n.is_deleted = 0
                      AND (n.expires_at IS NULL OR n.expires_at > CURRENT_TIMESTAMP)
                      AND (
                        n.scope = 'all'
                        OR (n.scope = 'user' AND n.recipient_username = %s)
                      )
                      AND r.dismissed_at IS NULL
                    LIMIT 1
                    ''',
                    (username, notification_id, username),
                )
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def mark_read(self, *, username: str, notification_id: int) -> None:
        if not self.visible_notification_exists(username=username, notification_id=notification_id):
            raise FileNotFoundError('未找到通知')
        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{receipts_table}` (
                      notification_id,
                      recipient_username,
                      read_at
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                      read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                      updated_at = CURRENT_TIMESTAMP
                    ''',
                    (notification_id, username),
                )
        finally:
            connection.close()

    def mark_all_read(self, *, username: str) -> None:
        notification_ids = self._list_visible_unread_ids(username)
        if not notification_ids:
            return

        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.executemany(
                    f'''
                    INSERT INTO `{receipts_table}` (
                      notification_id,
                      recipient_username,
                      read_at
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                      read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                      updated_at = CURRENT_TIMESTAMP
                    ''',
                    [(notification_id, username) for notification_id in notification_ids],
                )
        finally:
            connection.close()

    def dismiss(self, *, username: str, notification_id: int) -> None:
        if not self.visible_notification_exists(username=username, notification_id=notification_id):
            raise FileNotFoundError('未找到通知')
        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{receipts_table}` (
                      notification_id,
                      recipient_username,
                      read_at,
                      dismissed_at
                    ) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                      read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                      dismissed_at = CURRENT_TIMESTAMP,
                      updated_at = CURRENT_TIMESTAMP
                    ''',
                    (notification_id, username),
                )
        finally:
            connection.close()

    def delete_notification(self, *, notification_id: int) -> bool:
        notifications_table = self._notifications_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    UPDATE `{notifications_table}`
                    SET is_deleted = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    ''',
                    (notification_id,),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def _list_visible_unread_ids(self, username: str) -> list[int]:
        notifications_table = self._notifications_table_name()
        receipts_table = self._receipts_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT n.id
                    FROM `{notifications_table}` n
                    LEFT JOIN `{receipts_table}` r
                      ON r.notification_id = n.id
                     AND r.recipient_username = %s
                    WHERE n.is_deleted = 0
                      AND (n.expires_at IS NULL OR n.expires_at > CURRENT_TIMESTAMP)
                      AND (
                        n.scope = 'all'
                        OR (n.scope = 'user' AND n.recipient_username = %s)
                      )
                      AND r.read_at IS NULL
                      AND r.dismissed_at IS NULL
                    ''',
                    (username, username),
                )
                return [int(row['id']) for row in cursor.fetchall()]
        finally:
            connection.close()
