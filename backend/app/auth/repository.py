import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import AuthIdentity, AuthProvider, User, UserSession
from app.db.tenancy import UserScopedRepository, require_user_id


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def find_by_email(self, email: str) -> User | None:
        return self.session.scalars(
            select(User).where(func.lower(User.primary_email) == email.lower())
        ).one_or_none()

    def create(self, *, email: str, display_name: str | None) -> User:
        user = User(primary_email=email, display_name=display_name)
        self.session.add(user)
        self.session.flush()
        return user


class IdentityRepository(UserScopedRepository[AuthIdentity]):
    model = AuthIdentity

    def find_by_subject(self, *, provider: AuthProvider, subject: str) -> AuthIdentity | None:
        return self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.provider == provider, AuthIdentity.provider_subject == subject
            )
        ).one_or_none()

    def create(
        self,
        *,
        user_id: uuid.UUID,
        provider: AuthProvider,
        subject: str,
        email: str,
        now: datetime,
    ) -> AuthIdentity:
        identity = AuthIdentity(
            user_id=require_user_id(user_id),
            provider=provider,
            provider_subject=subject,
            email_at_login=email,
            last_login_at=now,
        )
        self.session.add(identity)
        self.session.flush()
        return identity


class SessionRepository(UserScopedRepository[UserSession]):
    model = UserSession

    def find_by_token_hash(self, token_hash: bytes) -> UserSession | None:
        return self.session.scalars(
            select(UserSession).where(UserSession.token_hash == token_hash)
        ).one_or_none()

    def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: bytes,
        now: datetime,
        expires_at: datetime,
        user_agent_hash: str | None,
    ) -> UserSession:
        row = UserSession(
            user_id=require_user_id(user_id),
            token_hash=token_hash,
            last_seen_at=now,
            expires_at=expires_at,
            user_agent_hash=user_agent_hash,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_user(self, *, user_id: uuid.UUID) -> Sequence[UserSession]:
        return self.session.scalars(
            select(UserSession)
            .where(UserSession.user_id == require_user_id(user_id))
            .order_by(UserSession.created_at.desc(), UserSession.id)
        ).all()

    def delete_row(self, row: UserSession) -> None:
        self.session.delete(row)
        self.session.flush()

    def delete_all_for_user(self, *, user_id: uuid.UUID) -> None:
        self.session.execute(
            delete(UserSession).where(UserSession.user_id == require_user_id(user_id))
        )
