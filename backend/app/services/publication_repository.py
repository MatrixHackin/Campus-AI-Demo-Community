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
                          app.id,
                          app.pod_name,
                          app.app_name,
                          app.app_description,
                          app.cover_url,
                          app.app_url,
                          app.owner_username,
                          app.owner_display_name,
                          app.visit_count,
                          app.like_count,
                          app.rating_avg,
                          app.rating_sum,
                          app.review_count,
                          CASE WHEN liked.id IS NULL THEN 0 ELSE 1 END AS is_liked,
                          my_review.id AS my_review_id,
                          my_review.username AS my_review_username,
                          my_review.display_name AS my_review_display_name,
                          my_review.rating AS my_review_rating,
                          my_review.comment AS my_review_comment,
                          my_review.created_at AS my_review_created_at,
                          my_review.updated_at AS my_review_updated_at,
                          app.published_at,
                          app.updated_at
                        FROM `{table_name}` app
                        LEFT JOIN `{likes_table_name}` liked
                          ON liked.publication_id = app.id AND liked.user_key = %s
                        LEFT JOIN `{reviews_table_name}` my_review
                          ON my_review.publication_id = app.id
                         AND my_review.user_key = %s
                         AND my_review.is_deleted = 0
                        WHERE app.is_published = 1
                        ORDER BY app.published_at DESC, app.id DESC
                        ''',
                        (user_key, user_key),
                    )
                else:
                    cursor.execute(
                        f'''
                        SELECT
                          id,
                          pod_name,
                          app_name,
                          app_description,
                          cover_url,
                          app_url,
                          owner_username,
                          owner_display_name,
                          visit_count,
                          like_count,
                          rating_avg,
                          rating_sum,
                          review_count,
                          0 AS is_liked,
                          NULL AS my_review_id,
                          NULL AS my_review_username,
                          NULL AS my_review_display_name,
                          NULL AS my_review_rating,
                          NULL AS my_review_comment,
                          NULL AS my_review_created_at,
                          NULL AS my_review_updated_at,
                          published_at,
                          updated_at
                        FROM `{table_name}`
                        WHERE is_published = 1
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
                      id,
                      pod_name,
                      app_name,
                      app_description,
                      cover_url,
                      app_url,
                      owner_username,
                      owner_display_name,
                      visit_count,
                      like_count,
                      rating_avg,
                      rating_sum,
                      review_count,
                      0 AS is_liked,
                      NULL AS my_review_id,
                      NULL AS my_review_username,
                      NULL AS my_review_display_name,
                      NULL AS my_review_rating,
                      NULL AS my_review_comment,
                      NULL AS my_review_created_at,
                      NULL AS my_review_updated_at,
                      published_at,
                      updated_at
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
                    WHERE pod_name IN ({placeholders}) AND is_published = 1
                    ''',
                    tuple(pod_names),
                )
                return {row['pod_name'] for row in cursor.fetchall()}
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
                      auth_provider
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                      is_published = 1,
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
        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT
                      id,
                      pod_name,
                      app_name,
                      app_description,
                      cover_url,
                      app_url,
                      owner_username,
                      owner_display_name,
                      visit_count,
                      like_count,
                      rating_avg,
                      rating_sum,
                      review_count,
                      0 AS is_liked,
                      NULL AS my_review_id,
                      NULL AS my_review_username,
                      NULL AS my_review_display_name,
                      NULL AS my_review_rating,
                      NULL AS my_review_comment,
                      NULL AS my_review_created_at,
                      NULL AS my_review_updated_at,
                      published_at,
                      updated_at
                    FROM `{table_name}`
                    WHERE id = %s AND is_published = 1
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
                    WHERE id = %s AND is_published = 1
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
                    WHERE id = %s AND is_published = 1
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

    @staticmethod
    def _lock_published_app(cursor, table_name: str, publication_id: int) -> bool:
        cursor.execute(
            f'''
            SELECT id
            FROM `{table_name}`
            WHERE id = %s AND is_published = 1
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
                            cover_url = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE pod_name = %s
                        ''',
                        (pod_name,),
                    )
        finally:
            connection.close()

        return row
