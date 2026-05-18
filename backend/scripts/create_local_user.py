#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.mysql import connect_mysql, validate_table_name  # noqa: E402

USERNAME_PATTERN = re.compile(r'[a-z_][a-z0-9_-]{0,31}')


def hash_password(password: str, iterations: int = 260000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations,
    ).hex()
    return f'pbkdf2_sha256${iterations}${salt}${digest}'


def generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + '-_@#'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
        ):
            return password


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not email or '@' not in email or len(email) > 255:
        raise ValueError('邮箱不合法')
    return email


def validate_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError('username 只能使用小写字母、数字、下划线和中划线，且必须以小写字母或下划线开头，最多 32 位')
    return username


def main() -> int:
    parser = argparse.ArgumentParser(description='Create an administrator-assigned local account in sso_users.')
    parser.add_argument('--email', required=True, help='邮箱，同时作为 Harbor 用户名')
    parser.add_argument('--username', required=True, help='登录账号，也是容器内 Linux/SSH 用户名，需避免与现有用户冲突')
    parser.add_argument('--emp-id', required=True, help='业务身份编号，用于 K3s namespace，需全局唯一')
    parser.add_argument('--display-name', default=None, help='显示名，默认使用 username')
    parser.add_argument('--department', default=None, help='部门/单位，可选')
    parser.add_argument('--user-type', default='local', help='用户类型，默认 local')
    parser.add_argument('--password', default=None, help='初始密码；不传则自动生成')
    args = parser.parse_args()

    email = normalize_email(args.email)
    username = validate_username(args.username)
    emp_id = args.emp_id.strip()
    if not emp_id:
        raise ValueError('emp-id 不能为空')

    generated_password = args.password is None
    password = args.password or generate_password()
    password_hash = hash_password(password)
    display_name = (args.display_name or username).strip()
    provider_subject = f'local:{email}'

    settings = get_settings()
    table_name = validate_table_name(settings.sso_user_table, '统一用户表名')
    connection = connect_mysql(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'''
                SELECT id, auth_provider, provider_subject, username, email, emp_id
                FROM `{table_name}`
                WHERE provider_subject = %s
                   OR username = %s
                   OR email = %s
                   OR emp_id = %s
                LIMIT 1
                ''',
                (provider_subject, username, email, emp_id),
            )
            conflict = cursor.fetchone()
            if conflict:
                raise RuntimeError(
                    '账号冲突：'
                    f'id={conflict.get("id")}, '
                    f'auth_provider={conflict.get("auth_provider")}, '
                    f'provider_subject={conflict.get("provider_subject")}, '
                    f'username={conflict.get("username")}, '
                    f'email={conflict.get("email")}, '
                    f'emp_id={conflict.get("emp_id")}'
                )

            cursor.execute(
                f'''
                INSERT INTO `{table_name}` (
                  auth_provider,
                  provider_subject,
                  username,
                  display_name,
                  user_type,
                  email,
                  department,
                  emp_id,
                  password_hash,
                  local_login_enabled,
                  last_login_at
                ) VALUES (
                  'local',
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  1,
                  NULL
                )
                ''',
                (
                    provider_subject,
                    username,
                    display_name,
                    args.user_type,
                    email,
                    args.department,
                    emp_id,
                    password_hash,
                ),
            )
            user_id = cursor.lastrowid
    finally:
        connection.close()

    print('本地账号创建成功：')
    print(f'  id: {user_id}')
    print(f'  email: {email}')
    print(f'  login_username: {username}')
    print(f'  emp_id: {emp_id}')
    if generated_password:
        print(f'  initial_password: {password}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
