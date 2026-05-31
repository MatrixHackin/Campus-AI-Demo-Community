from __future__ import annotations

import logging
from datetime import datetime

from app.core.config import Settings
from app.services.notification_event_bus import NotificationEventBus
from app.services.notification_repository import NotificationRepository
from app.services.token_store import SessionRecord

logger = logging.getLogger(__name__)

NOTIFICATION_TYPES = {
    'system_announcement',
    'admin_message',
    'review_rejected',
    'review_approved',
}
NOTIFICATION_SCOPES = {'all', 'user'}
TITLE_MAX_LENGTH = 120
CONTENT_MAX_LENGTH = 2000


class NotificationService:
    def __init__(self, settings: Settings, event_bus: NotificationEventBus | None = None) -> None:
        self.settings = settings
        self.repository = NotificationRepository(settings)
        self.event_bus = event_bus or NotificationEventBus()

    def list_user_notifications(
        self,
        *,
        session: SessionRecord,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        normalized_limit = min(100, max(1, limit))
        normalized_offset = max(0, offset)
        rows = self.repository.list_user_notifications(
            username=session.username,
            unread_only=unread_only,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return {
            'notifications': [self._serialize(row) for row in rows],
            'unread_count': self.repository.count_unread(username=session.username),
        }

    def get_unread_count(self, session: SessionRecord) -> dict:
        return {'unread_count': self.repository.count_unread(username=session.username)}

    def mark_read(self, notification_id: int, session: SessionRecord) -> dict:
        if notification_id <= 0:
            raise ValueError('通知 ID 不合法')
        self.repository.mark_read(username=session.username, notification_id=notification_id)
        self.event_bus.publish_changed(session.username)
        return self.get_unread_count(session)

    def mark_all_read(self, session: SessionRecord) -> dict:
        self.repository.mark_all_read(username=session.username)
        self.event_bus.publish_changed(session.username)
        return self.get_unread_count(session)

    def dismiss(self, notification_id: int, session: SessionRecord) -> dict:
        if notification_id <= 0:
            raise ValueError('通知 ID 不合法')
        self.repository.dismiss(username=session.username, notification_id=notification_id)
        self.event_bus.publish_changed(session.username)
        return self.get_unread_count(session)

    def list_admin_notifications(self, *, limit: int = 50, offset: int = 0) -> dict:
        rows = self.repository.list_admin_notifications(limit=min(100, max(1, limit)), offset=max(0, offset))
        return {'notifications': [self._serialize(row) for row in rows]}

    def create_admin_notification(
        self,
        *,
        title: str,
        content: str,
        notification_type: str,
        scope: str,
        sender_username: str,
        recipient_username: str | None = None,
        related_type: str | None = None,
        related_id: int | None = None,
        expires_at: str | None = None,
    ) -> dict:
        row = self._create_notification(
            title=title,
            content=content,
            notification_type=notification_type,
            scope=scope,
            sender_username=sender_username,
            recipient_username=recipient_username,
            related_type=related_type,
            related_id=related_id,
            expires_at=self._parse_expires_at(expires_at),
        )
        self.event_bus.publish_changed(row.get('recipient_username') if row.get('scope') == 'user' else None)
        return self._serialize(row)

    def notify_user(
        self,
        *,
        recipient_username: str,
        title: str,
        content: str,
        notification_type: str,
        sender_username: str | None = None,
        related_type: str | None = None,
        related_id: int | None = None,
    ) -> dict:
        row = self._create_notification(
            title=title,
            content=content,
            notification_type=notification_type,
            scope='user',
            sender_username=sender_username,
            recipient_username=recipient_username,
            related_type=related_type,
            related_id=related_id,
            expires_at=None,
        )
        self.event_bus.publish_changed(recipient_username)
        return self._serialize(row)

    def delete_admin_notification(self, notification_id: int) -> dict:
        if notification_id <= 0:
            raise ValueError('通知 ID 不合法')
        deleted = self.repository.delete_notification(notification_id=notification_id)
        if not deleted:
            raise FileNotFoundError('未找到通知')
        self.event_bus.publish_changed(None)
        return {'ok': True}

    def _create_notification(
        self,
        *,
        title: str,
        content: str,
        notification_type: str,
        scope: str,
        sender_username: str | None,
        recipient_username: str | None,
        related_type: str | None,
        related_id: int | None,
        expires_at: datetime | None,
    ) -> dict:
        normalized_title = title.strip()
        normalized_content = content.strip()
        normalized_type = notification_type.strip() or 'system_announcement'
        normalized_scope = scope.strip() or 'all'
        normalized_recipient = recipient_username.strip() if recipient_username else None
        normalized_related_type = related_type.strip() if related_type else None

        if not normalized_title:
            raise ValueError('通知标题不能为空')
        if len(normalized_title) > TITLE_MAX_LENGTH:
            raise ValueError(f'通知标题最多 {TITLE_MAX_LENGTH} 个字符')
        if not normalized_content:
            raise ValueError('通知内容不能为空')
        if len(normalized_content) > CONTENT_MAX_LENGTH:
            raise ValueError(f'通知内容最多 {CONTENT_MAX_LENGTH} 个字符')
        if normalized_type not in NOTIFICATION_TYPES:
            raise ValueError('通知类型不合法')
        if normalized_scope not in NOTIFICATION_SCOPES:
            raise ValueError('通知范围不合法')
        if normalized_scope == 'user' and not normalized_recipient:
            raise ValueError('指定用户通知需要填写接收用户名')
        if normalized_scope == 'all':
            normalized_recipient = None

        return self.repository.create_notification(
            title=normalized_title,
            content=normalized_content,
            notification_type=normalized_type,
            scope=normalized_scope,
            sender_username=sender_username,
            recipient_username=normalized_recipient,
            related_type=normalized_related_type,
            related_id=related_id,
            expires_at=expires_at,
        )

    @staticmethod
    def _parse_expires_at(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('过期时间格式不合法') from exc

    @staticmethod
    def _serialize(row: dict) -> dict:
        return {
            'id': int(row['id']),
            'title': row['title'],
            'content': row['content'],
            'type': row.get('notification_type') or row.get('type') or 'system_announcement',
            'scope': row.get('scope') or 'all',
            'recipient_username': row.get('recipient_username'),
            'sender_username': row.get('sender_username'),
            'related_type': row.get('related_type'),
            'related_id': row.get('related_id'),
            'read_at': row.get('read_at').isoformat() if row.get('read_at') else None,
            'dismissed_at': row.get('dismissed_at').isoformat() if row.get('dismissed_at') else None,
            'expires_at': row.get('expires_at').isoformat() if row.get('expires_at') else None,
            'created_at': row.get('created_at').isoformat() if row.get('created_at') else None,
            'updated_at': row.get('updated_at').isoformat() if row.get('updated_at') else None,
        }
