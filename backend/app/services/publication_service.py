from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings
from app.services.container_repository import ContainerRepository
from app.services.publication_repository import PublicationRepository
from app.services.token_store import SessionRecord

APP_DESCRIPTION_MAX_LENGTH = 40
APP_REVIEW_COMMENT_MAX_LENGTH = 300
logger = logging.getLogger(__name__)


class PublicationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.container_repository = ContainerRepository(settings)
        self.repository = PublicationRepository(settings)

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
        cover_file: BinaryIO | None,
        cover_content_type: str | None,
        session: SessionRecord,
    ) -> dict:
        description = app_description.strip()
        if not description:
            raise ValueError('请填写应用简述')
        if len(description) > APP_DESCRIPTION_MAX_LENGTH:
            raise ValueError(f'应用简述最多 {APP_DESCRIPTION_MAX_LENGTH} 个字符')

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

        row = self.repository.upsert_publication(
            pod_name=pod_name,
            app_name=app_name,
            app_description=description,
            cover_url=cover_url,
            app_url=f'{self.settings.k3s_apps_public_base_url}/{app_name}',
            owner_username=session.username,
            owner_display_name=session.display_name,
            auth_provider=session.auth_provider,
        )

        if cover_url and old_cover_url and cover_url != old_cover_url:
            self.delete_cover_by_url(old_cover_url)
        return self._serialize(row)

    def unpublish_app(self, *, pod_name: str, session: SessionRecord) -> dict | None:
        row = self.repository.get_by_pod_name(pod_name)
        if not row:
            return None
        if row.get('owner_username') != session.username:
            raise PermissionError('无权取消发布该应用')
        deleted = self.repository.delete_by_pod_name(pod_name, delete_likes=False)
        if deleted and deleted.get('cover_url'):
            self.delete_cover_by_url(deleted['cover_url'])
        return self._serialize(deleted) if deleted else None

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

    @staticmethod
    def _serialize(row: dict) -> dict:
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
            'owner_username': row['owner_username'],
            'owner_display_name': row.get('owner_display_name'),
            'visit_count': row.get('visit_count') or 0,
            'like_count': row.get('like_count') or 0,
            'is_liked': bool(row.get('is_liked')),
            'rating_avg': float(row.get('rating_avg') or 0),
            'rating_sum': int(row.get('rating_sum') or 0),
            'review_count': int(row.get('review_count') or 0),
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
