from datetime import UTC, datetime

import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import AuthIdentity, AuthProvider, UserSession, UserStatus
from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db


def add_auth_rows(session: Session, user_id: object) -> None:
    now = datetime.now(UTC)
    session.add(
        AuthIdentity(
            user_id=user_id,
            provider=AuthProvider.GOOGLE,
            provider_subject=new_id().hex,
            email_at_login="x@example.test",
            last_login_at=now,
        )
    )
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=new_id().bytes,
            last_seen_at=now,
            expires_at=now,
        )
    )
    session.flush()


COUNT_SQL = {
    table: text(f"SELECT count(*) FROM {table}")  # noqa: S608
    for table in ("users", "auth_identities", "sessions", "domain_events")
}


def count(session: Session, table: str) -> int:
    value: int = session.execute(COUNT_SQL[table]).scalar_one()
    return value


def test_provider_subject_is_unique(session: Session) -> None:
    first = make_user(session)
    second = make_user(session)
    now = datetime.now(UTC)
    for user in (first, second):
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.GOOGLE,
                provider_subject="same-subject",
                email_at_login="x@example.test",
                last_login_at=now,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_provider_is_restricted_to_google(session: Session) -> None:
    user = make_user(session)
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO auth_identities (id, user_id, provider, provider_subject, "
                "email_at_login, last_login_at) "
                "VALUES (:id, :user_id, 'github', 's', 'e', now())"
            ),
            {"id": new_id(), "user_id": user.id},
        )
    session.rollback()


def test_delete_function_refuses_active_user(session: Session) -> None:
    user = make_user(session)
    session.commit()

    deleted: bool = session.execute(
        text("SELECT delete_user_account(:id)"), {"id": user.id}
    ).scalar_one()
    session.commit()

    assert deleted is False
    assert count(session, "users") == 1


def test_delete_function_removes_only_the_target_user_and_cascades(session: Session) -> None:
    target = make_user(session)
    other = make_user(session)
    for user in (target, other):
        add_auth_rows(session, user.id)
        make_event(session, user.id)
    target.status = UserStatus.DELETION_REQUESTED
    session.commit()

    deleted: bool = session.execute(
        text("SELECT delete_user_account(:id)"), {"id": target.id}
    ).scalar_one()
    session.commit()

    assert deleted is True
    for table in ("users", "auth_identities", "sessions", "domain_events"):
        assert count(session, table) == 1
    remaining: object = session.execute(text("SELECT id FROM users")).scalar_one()
    assert remaining == other.id


def test_delete_function_returns_false_for_unknown_user(session: Session) -> None:
    assert (
        session.execute(text("SELECT delete_user_account(:id)"), {"id": new_id()}).scalar_one()
        is False
    )


def test_function_is_not_executable_by_public(owner_session: Session) -> None:
    acl: str = owner_session.execute(
        text("SELECT proacl::text FROM pg_proc WHERE proname = 'delete_user_account'")
    ).scalar_one()
    assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))
    assert "career_os_app=X" in acl


def test_function_pins_search_path(owner_session: Session) -> None:
    config: list[str] = owner_session.execute(
        text("SELECT proconfig FROM pg_proc WHERE proname = 'delete_user_account'")
    ).scalar_one()
    assert config == ["search_path=pg_catalog, public"]


def test_app_role_still_cannot_delete_users_directly(session: Session) -> None:
    make_user(session)
    session.commit()
    with pytest.raises(ProgrammingError) as error:
        session.execute(text("DELETE FROM users"))
    assert isinstance(error.value.orig, psycopg.errors.InsufficientPrivilege)
    session.rollback()
