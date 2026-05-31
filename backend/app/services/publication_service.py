from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from app.core.config import Settings
from app.services.app_page_renderer import render_share_page, render_unavailable_app_page
from app.services.container_repository import ContainerRepository
from app.services.notification_service import NotificationService
from app.services.platform_settings_repository import PlatformSettingsRepository
from app.services.publication_repository import PublicationRepository
from app.services.token_store import SessionRecord

APP_DESCRIPTION_MAX_LENGTH = 40
APP_REVIEW_COMMENT_MAX_LENGTH = 240
APP_PUBLISH_REVIEW_POLICY_KEY = 'app_publish_review_policy'
RESPONSIBILITY_ACK_VERSION_KEY = 'responsibility_ack_version'
REVIEW_POLICY_NO_REVIEW = 'no_review'
REVIEW_POLICY_REQUIRE_REVIEW = 'require_review'
logger = logging.getLogger(__name__)


class PublicationService:
    def __init__(
        self,
        settings: Settings,
        notification_service: NotificationService | None = None,
        k3s_service: Any | None = None,
    ) -> None:
        self.settings = settings
        self.container_repository = ContainerRepository(settings)
        self.repository = PublicationRepository(settings)
        self.platform_settings = PlatformSettingsRepository(settings)
        self.notification_service = notification_service
        self.k3s_service = k3s_service

    def list_public_apps(self, session: SessionRecord | None = None) -> dict:
        return {
            'apps': [
                self._serialize(row)
                for row in self.repository.list_public_apps(user_key=self._user_key(session) if session else None)
            ],
        }

    def publish_app(
        self,
        *,
        pod_name: str,
        app_description: str,
        responsibility_ack: bool,
        cover_file: BinaryIO | None,
        cover_content_type: str | None,
        session: SessionRecord,
    ) -> dict:
        description = app_description.strip()
        if not description:
            raise ValueError('请填写应用简述')
        if len(description) > APP_DESCRIPTION_MAX_LENGTH:
            raise ValueError(f'应用简述最多 {APP_DESCRIPTION_MAX_LENGTH} 个字符')
        if not responsibility_ack:
            raise ValueError('请先确认责任归属承诺知情书')

        record = self.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            raise FileNotFoundError('未找到容器记录')
        if record.get('username') != session.username:
            raise PermissionError('无权发布该应用')

        app_name = record.get('app_name')
        if not app_name:
            raise ValueError('容器记录缺少 app_name，无法发布')

        old_publication = self.repository.get_by_pod_name(pod_name)
        cover_url = old_publication.get('cover_url') if old_publication else None
        old_cover_url = cover_url
        if cover_file is not None:
            cover_url = self._save_cover_file(cover_file, cover_content_type)

        policy = self.get_review_policy()
        now = datetime.now()
        if policy == REVIEW_POLICY_REQUIRE_REVIEW:
            review_status = 'pending'
            is_published = False
            reviewed_at = None
            reviewed_by = None
            published_at = None
        else:
            review_status = 'approved'
            is_published = True
            reviewed_at = now
            reviewed_by = 'system'
            published_at = now

        row = self.repository.upsert_publication(
            pod_name=pod_name,
            app_name=app_name,
            app_description=description,
            cover_url=cover_url,
            app_url=f'{self.settings.k3s_apps_public_base_url}/{app_name}',
            owner_username=session.username,
            owner_display_name=session.display_name,
            auth_provider=session.auth_provider,
            review_status=review_status,
            is_published=is_published,
            submitted_at=now,
            reviewed_at=reviewed_at,
            reviewed_by=reviewed_by,
            responsibility_ack_version=self.get_responsibility_ack_version(),
            responsibility_ack_user_key=self._user_key(session),
            published_at=published_at,
        )

        if cover_url and old_cover_url and cover_url != old_cover_url:
            self.delete_cover_by_url(old_cover_url)
        self._sync_app_access_control(row, fail_closed=False)
        return self._serialize(row)

    def get_review_policy(self) -> str:
        value = self.platform_settings.get_value(APP_PUBLISH_REVIEW_POLICY_KEY, self.settings.app_publish_review_policy)
        return self._normalize_review_policy(value or self.settings.app_publish_review_policy)

    def get_responsibility_ack_version(self) -> str:
        return self.platform_settings.get_value(RESPONSIBILITY_ACK_VERSION_KEY, self.settings.responsibility_ack_version) or (
            self.settings.responsibility_ack_version
        )

    def get_review_settings(self) -> dict:
        return {
            'review_policy': self.get_review_policy(),
            'responsibility_ack_version': self.get_responsibility_ack_version(),
        }

    def list_publication_statuses(self, pod_names: list[str], session: SessionRecord) -> dict:
        normalized_pod_names = []
        seen = set()
        for pod_name in pod_names:
            normalized = (pod_name or '').strip()
            if normalized and normalized not in seen:
                normalized_pod_names.append(normalized)
                seen.add(normalized)

        rows = self.repository.get_publication_status_by_pod_names(
            normalized_pod_names,
            owner_username=session.username,
        )
        statuses = []
        for pod_name in normalized_pod_names:
            row = rows.get(pod_name)
            statuses.append({
                'pod_name': pod_name,
                'is_published': bool(row.get('is_published')) if row else False,
                'review_status': row.get('review_status') if row else 'unpublished',
                'submitted_at': row.get('submitted_at').isoformat() if row and row.get('submitted_at') else None,
                'reviewed_at': row.get('reviewed_at').isoformat() if row and row.get('reviewed_at') else None,
            })
        return {'statuses': statuses}

    def update_review_settings(
        self,
        *,
        review_policy: str,
        responsibility_ack_version: str | None,
        session: SessionRecord,
    ) -> dict:
        normalized_policy = self._normalize_review_policy(review_policy)
        self.platform_settings.set_value(APP_PUBLISH_REVIEW_POLICY_KEY, normalized_policy, session.username)
        if responsibility_ack_version is not None:
            version = responsibility_ack_version.strip()
            if not version:
                raise ValueError('责任承诺版本不能为空')
            if len(version) > 32:
                raise ValueError('责任承诺版本最多 32 个字符')
            self.platform_settings.set_value(RESPONSIBILITY_ACK_VERSION_KEY, version, session.username)
        return self.get_review_settings()

    def list_review_items(self, status_filter: str = 'pending') -> dict:
        if status_filter not in {'pending', 'approved', 'rejected', 'all'}:
            raise ValueError('审核状态参数不合法')
        return {
            'apps': [self._serialize(row) for row in self.repository.list_review_items(status_filter)],
        }

    def approve_publication(self, publication_id: int, session: SessionRecord, review_note: str | None = None) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        row = self.repository.approve_publication(
            publication_id,
            reviewed_by=session.username,
            review_note=(review_note or '').strip() or None,
        )
        if not row:
            raise FileNotFoundError('未找到待审核应用')
        self._sync_app_access_control(row, fail_closed=False)
        return self._serialize(row)

    def reject_publication(
        self,
        publication_id: int,
        session: SessionRecord,
        reject_reason: str,
        review_note: str | None = None,
    ) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        reason = reject_reason.strip()
        if not reason:
            raise ValueError('请填写拒绝原因')
        if len(reason) > 500:
            raise ValueError('拒绝原因最多 500 个字符')
        current = self.repository.get_by_id_any(publication_id)
        if not current:
            raise FileNotFoundError('未找到待审核应用')
        self._ensure_app_private_before_status_change(current)
        row = self.repository.reject_publication(
            publication_id,
            reviewed_by=session.username,
            reject_reason=reason,
            review_note=(review_note or '').strip() or None,
        )
        if not row:
            raise FileNotFoundError('未找到待审核应用')
        serialized = self._serialize(row)
        self._notify_review_rejected(serialized, reason, session)
        return serialized

    def unpublish_app(self, *, pod_name: str, session: SessionRecord) -> dict | None:
        row = self.repository.get_by_pod_name(pod_name)
        if not row:
            return None
        if row.get('owner_username') != session.username:
            raise PermissionError('无权取消发布该应用')
        self._ensure_app_private_before_status_change(row)
        old_cover_url = row.get('cover_url')
        deleted = self.repository.delete_by_pod_name(pod_name, delete_likes=False)
        if deleted and old_cover_url:
            self.delete_cover_by_url(old_cover_url)
        updated = self.repository.get_by_pod_name(pod_name) if deleted else None
        return self._serialize(updated or deleted) if deleted else None

    def record_visit(self, publication_id: int) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        row = self.repository.increment_visit_count(publication_id)
        if not row:
            raise FileNotFoundError('未找到发布应用')
        return self._serialize(row)

    def toggle_like(self, publication_id: int, session: SessionRecord) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        row = self.repository.toggle_like(
            publication_id=publication_id,
            user_key=self._user_key(session),
            username=session.username,
        )
        if not row:
            raise FileNotFoundError('未找到发布应用')
        return self._serialize(row)

    def get_reviews(
        self,
        publication_id: int,
        session: SessionRecord,
        offset: int = 0,
        limit: int = 10,
        sort: str = 'desc',
    ) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        if sort not in {'asc', 'desc'}:
            raise ValueError('评价排序参数不合法')
        row = self.repository.get_reviews(
            publication_id=publication_id,
            user_key=self._user_key(session),
            offset=offset,
            limit=limit,
            sort=sort,
        )
        if not row:
            raise FileNotFoundError('未找到发布应用')
        return self._serialize_reviews(row)

    def upsert_review(
        self,
        publication_id: int,
        rating: int,
        comment: str | None,
        session: SessionRecord,
    ) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        if rating < 0 or rating > 5:
            raise ValueError('评分必须在 0 到 5 星之间')

        normalized_comment = (comment or '').strip()
        if len(normalized_comment) > APP_REVIEW_COMMENT_MAX_LENGTH:
            raise ValueError(f'评论最多 {APP_REVIEW_COMMENT_MAX_LENGTH} 个字符')

        row = self.repository.upsert_review(
            publication_id=publication_id,
            user_key=self._user_key(session),
            username=session.username,
            display_name=session.display_name,
            rating=rating,
            comment=normalized_comment or None,
        )
        if not row:
            raise FileNotFoundError('未找到发布应用')
        return self._serialize_reviews(row)

    def delete_review(self, publication_id: int, session: SessionRecord) -> dict:
        if publication_id <= 0:
            raise ValueError('应用 ID 不合法')
        row = self.repository.delete_review(
            publication_id=publication_id,
            user_key=self._user_key(session),
        )
        if not row:
            raise FileNotFoundError('未找到发布应用')
        return self._serialize_reviews(row)

    def delete_cover_by_url(self, cover_url: str | None) -> None:
        if not cover_url:
            return
        public_prefix = self.settings.published_cover_public_prefix.rstrip('/') + '/'
        if not cover_url.startswith(public_prefix):
            return
        filename = cover_url.removeprefix(public_prefix)
        if '/' in filename or '\\' in filename:
            return
        path = self._cover_dir() / filename
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning('删除应用封面文件失败，已跳过：%s', exc)

    def _save_cover_file(self, file: BinaryIO, content_type: str | None) -> str:
        if content_type not in {'image/webp', 'image/jpeg', 'image/png'}:
            raise ValueError('封面仅支持 WebP、JPEG 或 PNG 图片')

        data = file.read(self.settings.published_cover_max_bytes + 1)
        if len(data) > self.settings.published_cover_max_bytes:
            max_kb = self.settings.published_cover_max_bytes // 1024
            raise ValueError(f'封面图片过大，请压缩到 {max_kb}KB 以内')

        extension = {
            'image/webp': '.webp',
            'image/jpeg': '.jpg',
            'image/png': '.png',
        }[content_type]
        filename = f'{uuid.uuid4().hex}{extension}'
        path = self._cover_dir() / filename
        path.write_bytes(data)
        return f'{self.settings.published_cover_public_prefix.rstrip("/")}/{filename}'

    def _cover_dir(self) -> Path:
        path = Path(self.settings.published_cover_storage_dir)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _user_key(session: SessionRecord) -> str:
        return session.user_id or f'{session.auth_provider}:{session.username}'

    def get_share_page(self, publication_id: int) -> tuple[int, str]:
        if publication_id <= 0:
            return 404, render_unavailable_app_page(
                title='应用不存在或不可访问',
                message='该分享链接无效或应用记录不存在。',
                home_url='/community',
            )

        row = self.repository.get_by_id_any(publication_id)
        if not row:
            return 404, render_unavailable_app_page(
                title='应用不存在或不可访问',
                message='该分享链接无效或应用记录不存在。',
                home_url='/community',
            )
        if not self._is_public(row):
            return 410, render_unavailable_app_page(
                title='应用已下架',
                message='该应用当前不可访问。',
                app_name=row.get('app_name'),
                home_url='/community',
            )

        app = self._serialize(row)
        return 200, render_share_page(
            app_name=app['app_name'],
            description=app.get('app_description') or '欢迎体验这个应用。',
            publisher=app.get('owner_display_name') or app.get('owner_username') or '用户',
            app_url=app['app_url'],
            share_url=app['share_url'],
            cover_url=self._absolute_url(app.get('cover_url')),
        )

    def share_url_for_publication_id(self, publication_id: int) -> str:
        return f'{self._platform_public_base_url()}/share/apps/{publication_id}'

    def _platform_public_base_url(self) -> str:
        apps_base_url = self.settings.k3s_apps_public_base_url.strip().rstrip('/')
        path_prefix = self.settings.k3s_apps_path_prefix.strip().rstrip('/') or '/apps'
        if apps_base_url.endswith(path_prefix):
            return apps_base_url[: -len(path_prefix)].rstrip('/') or apps_base_url
        parsed = urlparse(apps_base_url)
        if parsed.scheme and parsed.netloc:
            return f'{parsed.scheme}://{parsed.netloc}'
        return apps_base_url

    def _absolute_url(self, value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            return value
        return f'{self._platform_public_base_url()}/{value.lstrip("/")}'

    @staticmethod
    def _is_public(row: dict) -> bool:
        return bool(row.get('is_published')) and row.get('review_status') == 'approved'

    def _ensure_app_private_before_status_change(self, row: dict) -> None:
        app_name = row.get('app_name')
        if not app_name or not self.k3s_service:
            return
        try:
            self.k3s_service.set_app_access_control(app_name, enabled=True)
        except FileNotFoundError:
            logger.info('应用 %s 运行入口不存在，跳过访问控制收紧', app_name)
        except Exception as exc:
            logger.warning('应用 %s 收紧访问控制失败：%s', app_name, exc)
            raise RuntimeError(f'应用访问控制更新失败：{exc}') from exc

    def _sync_app_access_control(self, row: dict, *, fail_closed: bool) -> None:
        app_name = row.get('app_name')
        if not app_name or not self.k3s_service:
            return
        try:
            self.k3s_service.set_app_access_control(app_name, enabled=not self._is_public(row))
        except FileNotFoundError:
            logger.info('应用 %s 运行入口不存在，跳过访问控制同步', app_name)
        except Exception as exc:
            if fail_closed:
                raise RuntimeError(f'应用访问控制更新失败：{exc}') from exc
            logger.warning('应用 %s 访问控制同步失败，后续 reconcile 可修复：%s', app_name, exc)

    def _notify_review_rejected(self, publication: dict, reject_reason: str, session: SessionRecord) -> None:
        if not self.notification_service:
            return
        recipient_username = publication.get('owner_username')
        if not recipient_username:
            return
        try:
            self.notification_service.notify_user(
                recipient_username=recipient_username,
                title='应用审核未通过',
                content=f'你的应用「{publication.get("app_name") or publication.get("pod_name")}」审核未通过，原因：{reject_reason}',
                notification_type='review_rejected',
                sender_username=session.username,
                related_type='publication',
                related_id=publication.get('id'),
            )
        except Exception as exc:
            logger.warning('发送应用审核拒绝通知失败：%s', exc)

    @staticmethod
    def _normalize_review_policy(value: str) -> str:
        normalized = value.strip().lower().replace('-', '_')
        if normalized in {'no_review', 'require_review'}:
            return normalized
        raise ValueError('审核策略只能是不审核或都要审核')

    def _serialize(self, row: dict) -> dict:
        my_review = None
        if row.get('my_review_id'):
            my_review = {
                'id': int(row['my_review_id']),
                'username': row.get('my_review_username'),
                'display_name': row.get('my_review_display_name'),
                'rating': int(row.get('my_review_rating') or 0),
                'comment': row.get('my_review_comment'),
                'created_at': row.get('my_review_created_at').isoformat()
                if row.get('my_review_created_at') else None,
                'updated_at': row.get('my_review_updated_at').isoformat()
                if row.get('my_review_updated_at') else None,
            }
        return {
            'id': int(row['id']),
            'pod_name': row['pod_name'],
            'app_name': row['app_name'],
            'app_description': row.get('app_description'),
            'cover_url': row.get('cover_url'),
            'app_url': row['app_url'],
            'share_url': self.share_url_for_publication_id(int(row['id'])),
            'owner_username': row['owner_username'],
            'owner_display_name': row.get('owner_display_name'),
            'visit_count': row.get('visit_count') or 0,
            'like_count': row.get('like_count') or 0,
            'is_liked': bool(row.get('is_liked')),
            'rating_avg': float(row.get('rating_avg') or 0),
            'rating_sum': int(row.get('rating_sum') or 0),
            'review_count': int(row.get('review_count') or 0),
            'is_published': bool(row.get('is_published')),
            'review_status': row.get('review_status') or ('approved' if row.get('is_published') else 'unpublished'),
            'submitted_at': row.get('submitted_at').isoformat() if row.get('submitted_at') else None,
            'reviewed_at': row.get('reviewed_at').isoformat() if row.get('reviewed_at') else None,
            'reviewed_by': row.get('reviewed_by'),
            'review_note': row.get('review_note'),
            'reject_reason': row.get('reject_reason'),
            'responsibility_ack': bool(row.get('responsibility_ack')),
            'responsibility_ack_version': row.get('responsibility_ack_version'),
            'responsibility_ack_at': row.get('responsibility_ack_at').isoformat()
            if row.get('responsibility_ack_at') else None,
            'my_review': my_review,
            'published_at': row.get('published_at').isoformat() if row.get('published_at') else None,
            'updated_at': row.get('updated_at').isoformat() if row.get('updated_at') else None,
        }

    @classmethod
    def _serialize_reviews(cls, row: dict) -> dict:
        summary = row.get('summary') or {}
        return {
            'summary': {
                'rating_avg': float(summary.get('rating_avg') or 0),
                'rating_sum': int(summary.get('rating_sum') or 0),
                'review_count': int(summary.get('review_count') or 0),
            },
            'my_review': cls._serialize_review_item(row.get('my_review')),
            'reviews': [
                review
                for review in (cls._serialize_review_item(item) for item in row.get('reviews') or [])
                if review is not None
            ],
            'next_offset': row.get('next_offset'),
            'has_more': bool(row.get('has_more')),
            'sort': row.get('sort') or 'desc',
        }

    @staticmethod
    def _serialize_review_item(row: dict | None) -> dict | None:
        if not row:
            return None
        return {
            'id': int(row['id']) if row.get('id') is not None else None,
            'username': row.get('username'),
            'display_name': row.get('display_name'),
            'rating': int(row.get('rating') or 0),
            'comment': row.get('comment'),
            'created_at': row.get('created_at').isoformat() if row.get('created_at') else None,
            'updated_at': row.get('updated_at').isoformat() if row.get('updated_at') else None,
        }
