from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.domain.models import AuthenticatedUser, TenantMembership, UserAccount
from app.domain.ports import AuthRepository

SESSION_COOKIE = "serviceflow_session"
CSRF_COOKIE = "serviceflow_csrf"


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash("serviceflow-dummy-password")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerifyMismatchError):
            return False

    def verify_or_dummy(self, password_hash: str | None, password: str) -> bool:
        return self.verify(password_hash or self._dummy_hash, password)


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InMemoryAuthRepository:
    def __init__(self, users: list[UserAccount]) -> None:
        self._users = {user.email.casefold(): user for user in users}
        self._sessions: dict[str, tuple[str, str, datetime]] = {}

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        return self._users.get(email.casefold())

    async def create_session(
        self, user_id: str, token_hash: str, expires_at: datetime
    ) -> str:
        session_id = secrets.token_hex(16)
        self._sessions[token_hash] = (session_id, user_id, expires_at)
        return session_id

    async def get_session(
        self, token_hash: str, now: datetime
    ) -> AuthenticatedUser | None:
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        session_id, user_id, expires_at = session
        if expires_at <= now:
            self._sessions.pop(token_hash, None)
            return None
        user = next((item for item in self._users.values() if item.id == user_id), None)
        if user is None:
            return None
        return AuthenticatedUser(user.id, user.email, user.memberships, session_id)

    async def delete_session(self, session_id: str) -> None:
        for token_hash, session in list(self._sessions.items()):
            if session[0] == session_id:
                self._sessions.pop(token_hash, None)


def demo_user(passwords: PasswordService, email: str, password: str) -> UserAccount:
    return UserAccount(
        id="00000000-0000-0000-0000-000000000001",
        email=email.casefold(),
        password_hash=passwords.hash(password),
        memberships=(
            TenantMembership("ClinicaDental_01", "owner"),
            TenantMembership("Reformas_01", "admin"),
        ),
    )


def session_expiration(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
