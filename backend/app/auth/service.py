import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deletion import DELETE_ACCOUNT_JOB, DeleteAccountPayload, delete_account_unique_key
from app.auth.oidc import VerifiedIdentity
from app.auth.repository import IdentityRepository, SessionRepository, UserRepository
from app.auth.tokens import hash_token, hash_user_agent, new_session_token
from app.config import AuthSettings
from app.db.models import AuthProvider, User, UserSession, UserStatus
from app.jobs.queue import enqueue

LAST_SEEN_REFRESH = timedelta(minutes=5)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SignInError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AuthenticationFailed(Exception):
    def __init__(self, *, clear_cookies: bool) -> None:
        super().__init__("unauthenticated")
        self.clear_cookies = clear_cookies


@dataclass(frozen=True)
class AuthContext:
    user_id: uuid.UUID
    session_id: uuid.UUID


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session_id: uuid.UUID
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        session: Session,
        settings: AuthSettings,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = session
        self.settings = settings
        self.now = now
        self.users = UserRepository(session)
        self.identities = IdentityRepository(session)
        self.sessions = SessionRepository(session)

    def sign_in(self, identity: VerifiedIdentity, *, user_agent: str | None) -> IssuedSession:
        try:
            user = self._resolve_user(identity)
            issued = self._issue_session(user.id, user_agent)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise SignInError("sign_in_failed") from exc
        except SignInError:
            self.session.rollback()
            raise
        return issued

    def authenticate(self, token: str) -> AuthContext:
        row = self.sessions.find_by_token_hash(hash_token(token))
        if row is None:
            raise AuthenticationFailed(clear_cookies=False)
        now = self.now()
        user = self.users.get_by_id(row.user_id)
        idle_limit = timedelta(hours=self.settings.session_idle_timeout_hours)
        if (
            now >= row.expires_at
            or now - row.last_seen_at > idle_limit
            or user is None
            or user.status != UserStatus.ACTIVE
        ):
            self.sessions.delete_row(row)
            self.session.commit()
            raise AuthenticationFailed(clear_cookies=True)
        if now - row.last_seen_at >= LAST_SEEN_REFRESH:
            row.last_seen_at = now
            self.session.commit()
        return AuthContext(user_id=row.user_id, session_id=row.id)

    def get_user(self, user_id: uuid.UUID) -> User | None:
        return self.users.get_by_id(user_id)

    def list_sessions(self, *, user_id: uuid.UUID) -> Sequence[UserSession]:
        return self.sessions.list_for_user(user_id=user_id)

    def revoke(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        row = self.sessions.get(user_id=user_id, id=session_id)
        self.sessions.delete_row(row)
        self.session.commit()

    def request_deletion(self, *, user_id: uuid.UUID) -> None:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AuthenticationFailed(clear_cookies=True)
        user.status = UserStatus.DELETION_REQUESTED
        self.sessions.delete_all_for_user(user_id=user_id)
        enqueue(
            self.session,
            kind=DELETE_ACCOUNT_JOB,
            payload=DeleteAccountPayload(user_id=user_id),
            user_id=None,
            unique_key=delete_account_unique_key(user_id),
        )
        self.session.commit()

    def _resolve_user(self, identity: VerifiedIdentity) -> User:
        now = self.now()
        existing = self.identities.find_by_subject(
            provider=AuthProvider.GOOGLE, subject=identity.subject
        )
        if existing is not None:
            user = self.users.get_by_id(existing.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise SignInError("account_unavailable")
            existing.last_login_at = now
            existing.email_at_login = identity.email
            return user
        if self.users.find_by_email(identity.email) is not None:
            raise SignInError("account_conflict")
        user = self.users.create(email=identity.email, display_name=identity.name)
        self.identities.create(
            user_id=user.id,
            provider=AuthProvider.GOOGLE,
            subject=identity.subject,
            email=identity.email,
            now=now,
        )
        return user

    def _issue_session(self, user_id: uuid.UUID, user_agent: str | None) -> IssuedSession:
        now = self.now()
        token = new_session_token()
        expires_at = now + timedelta(hours=self.settings.session_absolute_timeout_hours)
        row = self.sessions.create(
            user_id=user_id,
            token_hash=hash_token(token),
            now=now,
            expires_at=expires_at,
            user_agent_hash=hash_user_agent(user_agent),
        )
        return IssuedSession(token=token, session_id=row.id, expires_at=expires_at)
