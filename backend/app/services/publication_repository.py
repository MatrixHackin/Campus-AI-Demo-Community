from __future__ import annotations

import logging

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name

logger = logging.getLogger(__name__)


class PublicationRepository:
    """应用市场发布记录访问封装。

    发布记录使用 username/auth_provider 作为所有者标识，兼容本地用户和 SSO 用户。
    封面只保存 URL，图片文件存储在本地 static/covers；后续可替换为图床/对象存储 URL。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _table_name() -> str:
        return validate_table_name('published_apps', '发布应用表名')

    @staticmethod
    def _likes_table_name() -> str:
        return validate_table_name('published_app_likes', '应用点赞表名')

    @staticmethod
    def _reviews_table_name() -> str:
        return validate_table_name('published_app_reviews', '应用评价表名')

    def _connect(self):
        return connect_mysql(self.settings)

    @staticmethod
    def _select_columns(prefix: str = 'app') -> str:
        return f'''
          {prefix}.id,
          {prefix}.pod_name,
          {prefix}.app_name,
          {prefix}.app_description,
          {prefix}.cover_url,
          {prefix}.app_url,
          {prefix}.owner_username,
          {prefix}.owner_display_name,
          {prefix}.visit_count,
          {prefix}.like_count,
          {prefix}.rating_avg,
          {prefix}.rating_sum,
          {prefix}.review_count,
          {prefix}.is_published,
          {prefix}.review_status,
          {prefix}.submitted_at,
          {prefix}.reviewed_at,
          {prefix}.reviewed_by,
          {prefix}.review_note,
          {prefix}.reject_reason,
          {prefix}.responsibility_ack,
          {prefix}.responsibility_ack_version,
          {prefix}.responsibility_ack_at,
          {prefix}.published_at,
          {prefix}.updated_at
        '''

    @classmethod
    def _select_columns_without_prefix(cls) -> str:
        return cls._select_columns('').replace('\n          .', '\n          ')

    def list_public_apps(self, user_key: str | None = None) -> list[dict]:
        table_name = self._table_name()
        likes_table_name = self._likes_table_name()
        reviews_table_name = self._reviews_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if user_key:
                    cursor.execute(
                        f'''
                        SELECT
                          {self._select_columns('app')},
                          CASE WHEN liked.id IS NULL THEN 0 ELSE 1 END AS is_liked,
                          my_review.id AS my_review_id,
                          my_review.username AS my_review_username,
                          my_review.display_name AS my_review_display_name,
                          my_review.rating AS my_review_rating,
                          my_review.comment AS my_review_comment,
                          my_review.created_at AS my_review_created_at,
                          my_review.updated_at AS my_review_updated_at
                        FROM `{table_name}` app
                        LEFT JOIN `{likes_table_name}` liked
                          ON liked.publication_id = app.id AND liked.user_key = %s
                        LEFT JOIN `{reviews_table_name}` my_review
                          ON my_review.publication_id = app.id
                         AND my_review.user_key = %s
                         AND my_review.is_deleted = 0
                        WHERE app.is_published = 1
                          AND app.review_status = 'approved'
                        ORDER BY app.published_at DESC, app.id DESC
                        ''',
                        (user_key, user_key),
                    )
                else:
                    cursor.execute(
                        f'''
                        SELECT
                          {self._select_columns_without_prefix()},
                          0 AS is_liked,
                          NULL AS my_review_id,
                          NULL AS my_review_username,
                          NULL AS my_review_display_name,
                          NULL AS my_review_rating,
                          NULL AS my_review_comment,
                          NULL AS my_review_created_at,
                          NULL AS my_review_updated_at
                        FROM `{table_name}`
                        WHERE is_published = 1
                          AND review_status = 'approved'
                        ORDER BY published_at DESC, id DESC
                        '''
                    )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def get_by_pod_name(self, pod_name: str) -> dict | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      {self._select_columns_without_prefix()},
                      0 AS is_liked,
                      NULL AS my_review_id,
                      NULL AS my_review_username,
                      NULL AS my_review_display_name,
                      NULL AS my_review_rating,
                      NULL AS my_review_comment,
                      NULL AS my_review_created_at,
                      NULL AS my_review_updated_at
                    FROM `{table_name}`
                    WHERE pod_name = %s
                    LIMIT 1
                    ''',
                    (pod_name,),
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def get_published_pod_names(self, pod_names: list[str]) -> set[str]:
        if not pod_names:
            return set()

        table_name = self._table_name()
        placeholders = ','.join(['%s'] * len(pod_names))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT pod_name
                    FROM `{table_name}`
                    WHERE pod_name IN ({placeholders})
                      AND is_published = 1
                      AND review_status = 'approved'
                    ''',
                    tuple(pod_names),
                )
                return {row['pod_name'] for row in cursor.fetchall()}
        finally:
            connection.close()

    def get_publication_status_by_pod_names(
        self,
        pod_names: list[str],
        *,
        owner_username: str | None = None,
    ) -> dict[str, dict]:
        if not pod_names:
            return {}

        table_name = self._table_name()
        placeholders = ','.join(['%s'] * len(pod_names))
        owner_clause = 'AND owner_username = %s' if owner_username else ''
        params = list(pod_names)
        if owner_username:
            params.append(owner_username)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      pod_name,
                      is_published,
                      review_status,
                      reject_reason,
                      submitted_at,
                      reviewed_at
                    FROM `{table_name}`
                    WHERE pod_name IN ({placeholders})
                      {owner_clause}
                    ''',
                    tuple(params),
                )
                return {row['pod_name']: row for row in cursor.fetchall()}
        finally:
            connection.close()

    def upsert_publication(
        self,
        *,
        pod_name: str,
        app_name: str,
        app_description: str,
        cover_url: str | None,
        app_url: str,
        owner_username: str,
        owner_display_name: str | None,
        auth_provider: str,
        review_status: str,
        is_published: bool,
        submitted_at,
        reviewed_at,
        reviewed_by: str | None,
        responsibility_ack_version: str,
        responsibility_ack_user_key: str,
        published_at,
        app_port: int = 3000,
    ) -> dict:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (
                      pod_name,
                      app_name,
                      app_description,
                      cover_url,
                      app_url,
                      app_port,
                      owner_username,
                      owner_display_name,
                      auth_provider,
                      is_published,
                      review_status,
                      submitted_at,
                      reviewed_at,
                      reviewed_by,
                      review_note,
                      reject_reason,
                      responsibility_ack,
                      responsibility_ack_version,
                      responsibility_ack_at,
                      responsibility_ack_user_key,
                      published_at
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, NULL, NULL, 1, %s, CURRENT_TIMESTAMP, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                      app_name = VALUES(app_name),
                      app_description = VALUES(app_description),
                      cover_url = VALUES(cover_url),
                      app_url = VALUES(app_url),
                      app_port = VALUES(app_port),
                      owner_username = VALUES(owner_username),
                      owner_display_name = VALUES(owner_display_name),
                      auth_provider = VALUES(auth_provider),
                      is_published = VALUES(is_published),
                      review_status = VALUES(review_status),
                      submitted_at = VALUES(submitted_at),
                      reviewed_at = VALUES(reviewed_at),
                      reviewed_by = VALUES(reviewed_by),
                      review_note = VALUES(review_note),
                      reject_reason = VALUES(reject_reason),
                      responsibility_ack = VALUES(responsibility_ack),
                      responsibility_ack_version = VALUES(responsibility_ack_version),
                      responsibility_ack_at = VALUES(responsibility_ack_at),
                      responsibility_ack_user_key = VALUES(responsibility_ack_user_key),
                      published_at = VALUES(published_at),
                      updated_at = CURRENT_TIMESTAMP,
                      id = LAST_INSERT_ID(id)
                    ''',
                    (
                        pod_name,
                        app_name,
                        app_description,
                        cover_url,
                        app_url,
                        app_port,
                        owner_username,
                        owner_display_name,
                        auth_provider,
                        int(is_published),
                        review_status,
                        submitted_at,
                        reviewed_at,
                        reviewed_by,
                        responsibility_ack_version,
                        responsibility_ack_user_key,
                        published_at,
                    ),
                )
                publication_id = cursor.lastrowid
        finally:
            connection.close()

        if publication_id:
            row = self.get_by_id(int(publication_id))
            if row:
                return row
        row = self.get_by_pod_name(pod_name)
        if not row:
            raise RuntimeError('发布记录写入后查询失败')
        return row

    def get_by_id(self, publication_id: int) -> dict | None:
        return self._get_by_id(publication_id, only_public=True)

    def get_by_id_any(self, publication_id: int) -> dict | None:
        return self._get_by_id(publication_id, only_public=False)

    def _get_by_id(self, publication_id: int, *, only_public: bool) -> dict | None:
        table_name = self._table_name()
        visibility_clause = "AND is_published = 1 AND review_status = 'approved'" if only_public else ''
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      {self._select_columns_without_prefix()},
                      0 AS is_liked,
                      NULL AS my_review_id,
                      NULL AS my_review_username,
                      NULL AS my_review_display_name,
                      NULL AS my_review_rating,
                      NULL AS my_review_comment,
                      NULL AS my_review_created_at,
                      NULL AS my_review_updated_at
                    FROM `{table_name}`
                    WHERE id = %s
                      {visibility_clause}
                    LIMIT 1
                    ''',
                    (publication_id,),
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def increment_visit_count(self, publication_id: int) -> dict | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    UPDATE `{table_name}`
                    SET visit_count = visit_count + 1
                    WHERE id = %s
                      AND is_published = 1
                      AND review_status = 'approved'
                    ''',
                    (publication_id,),
                )
        finally:
            connection.close()

        return self.get_by_id(publication_id)

    def toggle_like(self, publication_id: int, user_key: str, username: str | None) -> dict | None:
        table_name = self._table_name()
        likes_table_name = self._likes_table_name()
        connection = self._connect()
        is_liked = False
        try:
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT id
                    FROM `{table_name}`
                    WHERE id = %s
                      AND is_published = 1
                      AND review_status = 'approved'
                    LIMIT 1
                    FOR UPDATE
                    ''',
                    (publication_id,),
                )
                if not cursor.fetchone():
                    return None

                cursor.execute(
                    f'''
                    DELETE FROM `{likes_table_name}`
                    WHERE publication_id = %s AND user_key = %s
                    ''',
                    (publication_id, user_key),
                )
                if cursor.rowcount:
                    cursor.execute(
                        f'''
                        UPDATE `{table_name}`
                        SET like_count = GREATEST(like_count - 1, 0)
                        WHERE id = %s
                        ''',
                        (publication_id,),
                    )
                else:
                    cursor.execute(
                        f'''
                        INSERT INTO `{likes_table_name}` (
                          publication_id,
                          user_key,
                          username
                        ) VALUES (
                          %s,
                          %s,
                          %s
                        )
                        ''',
                        (publication_id, user_key, username),
                    )
                    cursor.execute(
                        f'''
                        UPDATE `{table_name}`
                        SET like_count = like_count + 1
                        WHERE id = %s
                        ''',
                        (publication_id,),
                    )
                    is_liked = True
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        row = self.get_by_id(publication_id)
        if row:
            row['is_liked'] = is_liked
        return row

    def upsert_review(
        self,
        *,
        publication_id: int,
        user_key: str,
        username: str | None,
        display_name: str | None,
        rating: int,
        comment: str | None,
    ) -> dict | None:
        table_name = self._table_name()
        reviews_table_name = self._reviews_table_name()
        connection = self._connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                if not self._lock_published_app(cursor, table_name, publication_id):
                    connection.rollback()
                    return None

                cursor.execute(
                    f'''
                    INSERT INTO `{reviews_table_name}` (
                      publication_id,
                      user_key,
                      username,
                      display_name,
                      rating,
                      comment,
                      is_deleted
                    ) VALUES (
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      0
                    )
                    ON DUPLICATE KEY UPDATE
                      username = VALUES(username),
                      display_name = VALUES(display_name),
                      rating = VALUES(rating),
                      comment = VALUES(comment),
                      is_deleted = 0,
                      updated_at = CURRENT_TIMESTAMP
                    ''',
                    (publication_id, user_key, username, display_name, rating, comment),
                )
                self._refresh_review_summary(cursor, table_name, reviews_table_name, publication_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return self.get_reviews(publication_id=publication_id, user_key=user_key)

    def delete_review(self, *, publication_id: int, user_key: str) -> dict | None:
        table_name = self._table_name()
        reviews_table_name = self._reviews_table_name()
        connection = self._connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                if not self._lock_published_app(cursor, table_name, publication_id):
                    connection.rollback()
                    return None
                cursor.execute(
                    f'''
                    UPDATE `{reviews_table_name}`
                    SET is_deleted = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE publication_id = %s
                      AND user_key = %s
                      AND is_deleted = 0
                    ''',
                    (publication_id, user_key),
                )
                self._refresh_review_summary(cursor, table_name, reviews_table_name, publication_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return self.get_reviews(publication_id=publication_id, user_key=user_key)

    def get_reviews(
        self,
        *,
        publication_id: int,
        user_key: str | None = None,
        offset: int = 0,
        limit: int = 10,
        sort: str = 'desc',
    ) -> dict | None:
        table_name = self._table_name()
        reviews_table_name = self._reviews_table_name()
        normalized_limit = max(1, min(int(limit), 50))
        normalized_offset = max(0, int(offset))
        sort_direction = 'ASC' if sort == 'asc' else 'DESC'
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT id, rating_avg, rating_sum, review_count
                    FROM `{table_name}`
                    WHERE id = %s
                      AND is_published = 1
                      AND review_status = 'approved'
                    LIMIT 1
                    ''',
                    (publication_id,),
                )
                app = cursor.fetchone()
                if not app:
                    return None

                my_review = None
                if user_key:
                    cursor.execute(
                        f'''
                        SELECT
                          id,
                          username,
                          display_name,
                          rating,
                          comment,
                          created_at,
                          updated_at
                        FROM `{reviews_table_name}`
                        WHERE publication_id = %s
                          AND user_key = %s
                          AND is_deleted = 0
                        LIMIT 1
                        ''',
                        (publication_id, user_key),
                    )
                    my_review = cursor.fetchone()

                cursor.execute(
                    f'''
                    SELECT
                      id,
                      username,
                      display_name,
                      rating,
                      comment,
                      created_at,
                      updated_at
                    FROM `{reviews_table_name}`
                    WHERE publication_id = %s
                      AND is_deleted = 0
                    ORDER BY rating {sort_direction}, updated_at DESC, id DESC
                    LIMIT %s
                    OFFSET %s
                    ''',
                    (publication_id, normalized_limit + 1, normalized_offset),
                )
                fetched_reviews = list(cursor.fetchall())
        finally:
            connection.close()

        has_more = len(fetched_reviews) > normalized_limit
        reviews = fetched_reviews[:normalized_limit]

        return {
            'summary': {
                'rating_avg': app.get('rating_avg') or 0,
                'rating_sum': app.get('rating_sum') or 0,
                'review_count': app.get('review_count') or 0,
            },
            'my_review': my_review,
            'reviews': reviews,
            'next_offset': normalized_offset + len(reviews) if has_more else None,
            'has_more': has_more,
            'sort': sort if sort in {'asc', 'desc'} else 'desc',
        }

    def list_review_items(self, status_filter: str = 'pending') -> list[dict]:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if status_filter == 'all':
                    cursor.execute(
                        f'''
                        SELECT
                          {self._select_columns_without_prefix()},
                          0 AS is_liked,
                          NULL AS my_review_id,
                          NULL AS my_review_username,
                          NULL AS my_review_display_name,
                          NULL AS my_review_rating,
                          NULL AS my_review_comment,
                          NULL AS my_review_created_at,
                          NULL AS my_review_updated_at
                        FROM `{table_name}`
                        WHERE review_status IN ('pending', 'approved', 'rejected')
                        ORDER BY submitted_at DESC, updated_at DESC, id DESC
                        '''
                    )
                else:
                    cursor.execute(
                        f'''
                        SELECT
                          {self._select_columns_without_prefix()},
                          0 AS is_liked,
                          NULL AS my_review_id,
                          NULL AS my_review_username,
                          NULL AS my_review_display_name,
                          NULL AS my_review_rating,
                          NULL AS my_review_comment,
                          NULL AS my_review_created_at,
                          NULL AS my_review_updated_at
                        FROM `{table_name}`
                        WHERE review_status = %s
                        ORDER BY submitted_at DESC, updated_at DESC, id DESC
                        ''',
                        (status_filter,),
                    )
                return list(cursor.fetchall())
        finally:
            connection.close()

    def approve_publication(self, publication_id: int, *, reviewed_by: str, review_note: str | None = None) -> dict | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    UPDATE `{table_name}`
                    SET review_status = 'approved',
                        is_published = 1,
                        reviewed_at = CURRENT_TIMESTAMP,
                        reviewed_by = %s,
                        review_note = %s,
                        reject_reason = NULL,
                        published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    ''',
                    (reviewed_by, review_note, publication_id),
                )
        finally:
            connection.close()
        return self.get_by_id_any(publication_id)

    def reject_publication(
        self,
        publication_id: int,
        *,
        reviewed_by: str,
        reject_reason: str,
        review_note: str | None = None,
    ) -> dict | None:
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    UPDATE `{table_name}`
                    SET review_status = 'rejected',
                        is_published = 0,
                        reviewed_at = CURRENT_TIMESTAMP,
                        reviewed_by = %s,
                        review_note = %s,
                        reject_reason = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    ''',
                    (reviewed_by, review_note, reject_reason, publication_id),
                )
        finally:
            connection.close()
        return self.get_by_id_any(publication_id)

    @staticmethod
    def _lock_published_app(cursor, table_name: str, publication_id: int) -> bool:
        cursor.execute(
            f'''
            SELECT id
            FROM `{table_name}`
            WHERE id = %s
              AND is_published = 1
              AND review_status = 'approved'
            LIMIT 1
            FOR UPDATE
            ''',
            (publication_id,),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _refresh_review_summary(cursor, table_name: str, reviews_table_name: str, publication_id: int) -> None:
        cursor.execute(
            f'''
            SELECT
              COUNT(*) AS review_count,
              COALESCE(SUM(rating), 0) AS rating_sum,
              COALESCE(AVG(rating), 0) AS rating_avg
            FROM `{reviews_table_name}`
            WHERE publication_id = %s
              AND is_deleted = 0
            ''',
            (publication_id,),
        )
        summary = cursor.fetchone() or {}
        cursor.execute(
            f'''
            UPDATE `{table_name}`
            SET review_count = %s,
                rating_sum = %s,
                rating_avg = %s
            WHERE id = %s
            ''',
            (
                int(summary.get('review_count') or 0),
                int(summary.get('rating_sum') or 0),
                summary.get('rating_avg') or 0,
                publication_id,
            ),
        )

    def delete_by_pod_name(self, pod_name: str, delete_likes: bool = False) -> dict | None:
        row = self.get_by_pod_name(pod_name)
        if not row:
            return None

        table_name = self._table_name()
        likes_table_name = self._likes_table_name()
        reviews_table_name = self._reviews_table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if delete_likes:
                    cursor.execute(
                        f'''
                        DELETE FROM `{likes_table_name}`
                        WHERE publication_id = %s
                        ''',
                        (row['id'],),
                    )
                    cursor.execute(
                        f'''
                        DELETE FROM `{reviews_table_name}`
                        WHERE publication_id = %s
                        ''',
                        (row['id'],),
                    )
                    cursor.execute(
                        f'''
                        DELETE FROM `{table_name}`
                        WHERE pod_name = %s
                        ''',
                        (pod_name,),
                    )
                else:
                    cursor.execute(
                        f'''
                        UPDATE `{table_name}`
                        SET is_published = 0,
                            review_status = 'unpublished',
                            cover_url = NULL,
                            reject_reason = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE pod_name = %s
                        ''',
                        (pod_name,),
                    )
        finally:
            connection.close()

        return row
