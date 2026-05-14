from __future__ import annotations

import argparse
import hashlib
from secrets import token_hex


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate a PBKDF2-SHA256 password_hash for campus AI users.')
    parser.add_argument('password')
    parser.add_argument('--iterations', type=int, default=260000)
    parser.add_argument('--salt', default=None)
    args = parser.parse_args()

    salt = args.salt or token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        args.password.encode('utf-8'),
        salt.encode('utf-8'),
        args.iterations,
    ).hex()

    print(f'pbkdf2_sha256${args.iterations}${salt}${digest}')


if __name__ == '__main__':
    main()
