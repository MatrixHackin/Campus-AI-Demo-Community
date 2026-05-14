from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Lock


@dataclass(slots=True)
class SessionRecord:
    token: str
    user_id: str
    username: str
    display_name: str
    expires_at: datetime


class TokenStore:
    def __init__(self, ttl_hours: int = 12) -> None:
        self.ttl_hours = ttl_hours
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = Lock()

    def issue_token(self, user_id: str, username: str, display_name: str) -> SessionRecord:
        token = token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        session = SessionRecord(
            token=token,
            user_id=user_id,
            username=username,
            display_name=display_name,
            expires_at=expires_at,
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def get_session(self, token: str) -> SessionRecord | None:
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if session.expires_at <= datetime.now(timezone.utc):
                self._sessions.pop(token, None)
                return None
            return session
