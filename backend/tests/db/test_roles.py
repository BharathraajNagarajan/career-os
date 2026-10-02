import os

import psycopg.errors
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.bootstrap import APP_ROLE, bootstrap
from tests.db.conftest import Database, secret
from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db


def assert_denied(session: Session, statement: str) -> None:
    with pytest.raises(ProgrammingError) as error:
        session.execute(text(statement))
    assert isinstance(error.value.orig, psycopg.errors.InsufficientPrivilege)
    session.rollback()


def test_app_role_can_insert_and_select_events(session: Session) -> None:
    user = make_user(session)
    event = make_event(session, user.id)
    session.commit()

    count: int = session.execute(
        text("SELECT count(*) FROM domain_events WHERE id = :id"), {"id": event.id}
    ).scalar_one()
    assert count == 1


def test_app_role_cannot_update_or_delete_events(session: Session) -> None:
    user = make_user(session)
    make_event(session, user.id)
    session.commit()

    assert_denied(session, "UPDATE domain_events SET event_type = 'changed'")
    assert_denied(session, "DELETE FROM domain_events")
    assert_denied(session, "TRUNCATE domain_events")


def test_app_role_cannot_delete_users(session: Session) -> None:
    make_user(session)
    session.commit()

    assert_denied(session, "DELETE FROM users")


def test_app_role_has_login_and_no_other_attributes(owner_session: Session) -> None:
    row = owner_session.execute(
        text(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
            "rolbypassrls FROM pg_roles WHERE rolname = :role"
        ),
        {"role": APP_ROLE},
    ).one()

    assert tuple(row) == (True, False, False, False, False, False)


def test_app_role_cannot_change_schema(session: Session) -> None:
    assert_denied(session, "CREATE TABLE intruder (id int)")
    assert_denied(session, "ALTER TABLE domain_events ADD COLUMN extra text")


def test_bootstrap_is_idempotent(database: Database) -> None:
    password = SecretStr(os.environ["APP_DB_PASSWORD"])
    bootstrap(secret(database.owner_url), password)
    bootstrap(secret(database.owner_url), password)

    with database.app.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == APP_ROLE
