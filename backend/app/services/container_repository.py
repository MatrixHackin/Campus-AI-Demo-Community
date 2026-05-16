from __future__ import annotations

import logging
import re

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ContainerRepository:
    """containers 表访问封装。

    当前用于保存容器申请记录，并通过 containers.app_name 唯一索引保证应用名全局唯一。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _table_name() -> str:
        table_name = 'containers'
        if not re.fullmatch(r'[A-Za-z0-9_]+', table_name):
            raise ValueError('容器表名配置不合法')
        return table_name

    def _connect(self):
        import pymysql
        from pymysql.cursors import DictCursor

        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_database,
            charset=self.settings.mysql_charset,
            cursorclass=DictCursor,
            autocommit=True,
        )

    def app_name_exists(self, app_name: str) -> bool:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            raise RuntimeError(f'连接容器记录数据库失败：{exc}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT id
                    FROM `{table_name}`
                    WHERE app_name = %s
                    LIMIT 1
                    ''',
                    (app_name,),
                )
                return cursor.fetchone() is not None
        except Exception as exc:
            raise RuntimeError(f'查询应用名称失败：{exc}') from exc
        finally:
            connection.close()

    def create_container_record(
        self,
        *,
        pod_name: str,
        username: str,
        password: str,
        app_name: str,
    ) -> None:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            raise RuntimeError(f'连接容器记录数据库失败：{exc}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    INSERT INTO `{table_name}` (
                      pod_name,
                      app_name,
                      username,
                      password
                    ) VALUES (
                      %s,
                      %s,
                      %s,
                      %s
                    )
                    ''',
                    (pod_name, app_name, username, password),
                )
        except Exception as exc:
            if self._is_duplicate_key_error(exc):
                raise FileExistsError('该应用名称或 Pod 名称已被使用') from exc
            raise RuntimeError(f'写入容器记录失败：{exc}') from exc
        finally:
            connection.close()

    def delete_container_record(self, *, pod_name: str) -> None:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            logger.warning('连接容器记录数据库失败，跳过删除容器记录：%s', exc)
            return

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

    @staticmethod
    def _is_duplicate_key_error(exc: Exception) -> bool:
        return bool(getattr(exc, 'args', None)) and exc.args[0] == 1062
