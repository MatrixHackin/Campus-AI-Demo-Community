from __future__ import annotations

import base64
import hashlib
import json
import logging
from secrets import token_urlsafe
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def generate_code_verifier() -> str:
    return _base64_url_encode(token_urlsafe(64).encode('ascii'))[:128]


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    return _base64_url_encode(digest)


class SSOService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def domain(self) -> str:
        return self.settings.sso_domain.rstrip('/')

    def build_authorize_url(self, state: str, code_challenge: str) -> str:
        query = urlencode(
            {
                'client_id': self.settings.sso_client_id,
                'client_secret': self.settings.sso_client_secret,
                'redirect_uri': self.settings.sso_redirect_uri,
                'response_type': 'code',
                'response_mode': 'query',
                'scope': self.settings.sso_scope,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
            }
        )
        return f'{self.domain}/connect/authorize?{query}'

    def exchange_code_for_token(self, code: str, code_verifier: str) -> dict[str, Any]:
        form = urlencode(
            {
                'client_id': self.settings.sso_client_id,
                'client_secret': self.settings.sso_client_secret,
                'redirect_uri': self.settings.sso_redirect_uri,
                'grant_type': 'authorization_code',
                'code': code,
                'code_verifier': code_verifier,
            }
        ).encode('utf-8')

        request = Request(
            f'{self.domain}/connect/token',
            data=form,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        return self._read_json(request, 'SSO token endpoint 调用失败')

    def get_userinfo(self, access_token: str) -> dict[str, Any]:
        request = Request(
            f'{self.domain}/connect/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            method='POST',
        )
        return self._read_json(request, 'SSO userinfo endpoint 调用失败')

    def build_logout_url(self, id_token: str) -> str:
        query = urlencode(
            {
                'id_token_hint': id_token,
                'post_logout_redirect_uri': self.settings.sso_post_logout_redirect_uri,
            }
        )
        return f'{self.domain}/connect/endsession?{query}'

    def _read_json(self, request: Request, error_message: str) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=15) as response:
                body = response.read().decode('utf-8')
        except HTTPError as exc:
            logger.warning('%s: HTTP %s', error_message, exc.code)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_message) from exc
        except URLError as exc:
            logger.warning('%s: network error', error_message)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_message) from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.warning('%s: invalid JSON response', error_message)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_message) from exc

        if not isinstance(data, dict):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error_message)
        return data
