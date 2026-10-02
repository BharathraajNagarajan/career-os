import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import DomainEvent, User, UserStatus
from tests.db.conftest import Database, alembic_config
from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db


def test_models_match_migrations(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL", database.owner_url.render_as_string(hide_password=False)
    )

    command.check(alembic_config())


def test_cross_user_void_reference_is_rejected_by_composite_fk(session: Session) -> None:
    owner = make_user(session)
    other = make_user(session)
    foreign_event = make_event(session, other.id)
    session.commit()

    with pytest.raises(IntegrityError) as error:
        make_event(session, owner.id, voids_event_id=foreign_event.id)
    assert "fk_domain_events_user_id_voids_event_id_domain_events" in str(error.value.orig)


def test_same_user_void_reference_is_accepted(session: Session) -> None:
    user = make_user(session)
    original = make_event(session, user.id)
    correction = make_event(session, user.id, voids_event_id=original.id)
    session.commit()

    assert correction.voids_event_id == original.id


def test_primary_email_is_unique_case_insensitively(session: Session) -> None:
    session.add(User(primary_email="Person@Example.test"))
    session.flush()
    session.add(User(primary_email="person@example.TEST"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_enum_check_constraint_rejects_unknown_values(session: Session) -> None:
    user = make_user(session)
    session.commit()

    with pytest.raises(IntegrityError) as error:
        session.execute(
            text(
                "INSERT INTO domain_events (id, user_id, aggregate_type, aggregate_id, event_type,"
                " occurred_at, actor, payload) VALUES (:id, :user_id, 'resume', :id, 'x', now(),"
                " 'user', '{}')"
            ),
            {"id": new_id(), "user_id": user.id},
        )
    assert "ck_domain_events_aggregate_type" in str(error.value.orig)


def test_server_defaults_are_applied(session: Session) -> None:
    user = make_user(session)
    event = make_event(session, user.id)
    session.commit()
    session.refresh(user)

    assert user.status is UserStatus.ACTIVE
    assert user.created_at.tzinfo is not None
    assert event.recorded_at is not None


def test_deleting_a_user_cascades_to_events(session: Session, owner_session: Session) -> None:
    user = make_user(session)
    original = make_event(session, user.id)
    make_event(session, user.id, voids_event_id=original.id)
    session.commit()

    owner_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    owner_session.commit()

    remaining = session.scalars(select(DomainEvent).where(DomainEvent.user_id == user.id)).all()
    assert remaining == []
