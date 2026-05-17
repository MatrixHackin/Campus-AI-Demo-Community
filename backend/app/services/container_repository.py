from __future__ import annotations

import logging

from app.core.config import Settings
from app.db.mysql import connect_mysql, validate_table_name

logger = logging.getLogger(__name__)


class ContainerRepository:
    """containers 表访问封装。

    当前用于保存容器申请记录，并通过 containers.app_name 唯一索引保证应用名全局唯一。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _table_name() -> str:
        return validate_table_name('containers', '容器表名')

    def _connect(self):
        return connect_mysql(self.settings)

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
        namespace: str,
        ssh_username: str,
        ssh_service_name: str,
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
                      namespace,
                      username,
                      password,
                      ssh_username,
                      ssh_service_name
                    ) VALUES (
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      %s,
                      %s
                    )
                    ''',
                    (pod_name, app_name, namespace, username, password, ssh_username, ssh_service_name),
                )
        except Exception as exc:
            if self._is_duplicate_key_error(exc):
                raise FileExistsError('该应用名称或 Pod 名称已被使用') from exc
            raise RuntimeError(f'写入容器记录失败：{exc}') from exc
        finally:
            connection.close()

    def get_container_record(self, *, pod_name: str) -> dict | None:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            raise RuntimeError(f'连接容器记录数据库失败：{exc}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT pod_name, app_name, namespace, username, password, ssh_username, ssh_service_name
                    FROM `{table_name}`
                    WHERE pod_name = %s
                    LIMIT 1
                    ''',
                    (pod_name,),
                )
                return cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(f'查询容器记录失败：{exc}') from exc
        finally:
            connection.close()

    def get_container_record_by_app_name(self, *, app_name: str) -> dict | None:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            raise RuntimeError(f'连接容器记录数据库失败：{exc}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    SELECT pod_name, app_name, namespace, username, password, ssh_username, ssh_service_name
                    FROM `{table_name}`
                    WHERE app_name = %s
                    LIMIT 1
                    ''',
                    (app_name,),
                )
                return cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(f'查询容器记录失败：{exc}') from exc
        finally:
            connection.close()

    def delete_container_record(self, *, pod_name: str, suppress_errors: bool = False) -> None:
        table_name = self._table_name()
        try:
            connection = self._connect()
        except Exception as exc:
            if suppress_errors:
                logger.warning('连接容器记录数据库失败，跳过删除容器记录：%s', exc)
                return
            raise RuntimeError(f'连接容器记录数据库失败：{exc}') from exc

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'''
                    DELETE FROM `{table_name}`
                    WHERE pod_name = %s
                    ''',
                    (pod_name,),
                )
        except Exception as exc:
            if suppress_errors:
                logger.warning('删除容器记录失败，跳过：%s', exc)
                return
            raise RuntimeError(f'删除容器记录失败：{exc}') from exc
        finally:
            connection.close()

    @staticmethod
    def _is_duplicate_key_error(exc: Exception) -> bool:
        return bool(getattr(exc, 'args', None)) and exc.args[0] == 1062
