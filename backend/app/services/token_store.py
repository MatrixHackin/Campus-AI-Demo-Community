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
    auth_provider: str = 'local'
    id_token: str | None = None
    access_token: str | None = None


@dataclass(slots=True)
class OAuthStateRecord:
    state: str
    code_verifier: str
    expires_at: datetime


class TokenStore:
    def __init__(self, ttl_hours: int = 12) -> None:
        self.ttl_hours = ttl_hours
        self._sessions: dict[str, SessionRecord] = {}
        self._oauth_states: dict[str, OAuthStateRecord] = {}
        self._lock = Lock()

    def issue_token(
        self,
        user_id: str,
        username: str,
        display_name: str,
        auth_provider: str = 'local',
        id_token: str | None = None,
        access_token: str | None = None,
    ) -> SessionRecord:
        token = token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        session = SessionRecord(
            token=token,
            user_id=user_id,
            username=username,
            display_name=display_name,
            expires_at=expires_at,
            auth_provider=auth_provider,
            id_token=id_token,
            access_token=access_token,
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

    def revoke_session(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def issue_oauth_state(self, code_verifier: str, ttl_minutes: int = 10) -> str:
        state = token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        with self._lock:
            self._oauth_states[state] = OAuthStateRecord(
                state=state,
                code_verifier=code_verifier,
                expires_at=expires_at,
            )
        return state

    def consume_oauth_state(self, state: str) -> OAuthStateRecord | None:
        with self._lock:
            record = self._oauth_states.pop(state, None)
        if not record:
            return None
        if record.expires_at <= datetime.now(timezone.utc):
            return None
        return record
