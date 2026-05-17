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

    def _connect(self):
        return connect_mysql(self.settings)

    def list_public_apps(self) -> list[dict]:
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
                      published_at,
                      updated_at
                    FROM `{table_name}`
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
                    WHERE pod_name IN ({placeholders})
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
                      published_at,
                      updated_at
                    FROM `{table_name}`
                    WHERE id = %s
                    LIMIT 1
                    ''',
                    (publication_id,),
                )
                return cursor.fetchone()
        finally:
            connection.close()

    def delete_by_pod_name(self, pod_name: str) -> dict | None:
        row = self.get_by_pod_name(pod_name)
        if not row:
            return None

        table_name = self._table_name()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    DELETE FROM `{table_name}`
                    WHERE pod_name = %s
                    ''',
                    (pod_name,),
                )
        finally:
            connection.close()

        return row
