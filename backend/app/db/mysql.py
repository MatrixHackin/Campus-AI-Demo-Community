from __future__ import annotations

import re

from app.core.config import Settings


def validate_table_name(table_name: str, label: str = '表名') -> str:
    if not re.fullmatch(r'[A-Za-z0-9_]+', table_name):
        raise ValueError(f'{label}配置不合法')
    return table_name


def connect_mysql(settings: Settings):
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset=settings.mysql_charset,
        cursorclass=DictCursor,
        autocommit=True,
    )
