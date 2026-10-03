import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationChannel, ApplicationStage, Resume, ResumeLane
from tests.db.factories import make_user
from tests.db.test_opportunity_schema import make_artifact, make_opportunity
from tests.db.test_roles import assert_denied

pytestmark = pytest.mark.db


def make_application(
    session: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID, **extra: Any
) -> Application:
    row = Application(
        user_id=user_id, opportunity_id=opportunity_id, applied_at=datetime.now(UTC), **extra
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def user_id(session: Session) -> uuid.UUID:
    user = make_user(session)
    session.commit()
    return user.id


def test_defaults_match_the_spec(session: Session, user_id: uuid.UUID) -> None:
    opportunity = make_opportunity(session, user_id)
    row = make_application(session, user_id, opportunity.id)
    session.commit()
    session.refresh(row)

    assert row.stage is ApplicationStage.APPLIED
    assert row.is_terminal is False
    assert row.channel is ApplicationChannel.OTHER
    assert row.state_version == 1
    assert row.resume_id is None
    assert row.lane_id is None
    assert row.created_at is not None
    assert row.updated_at is not None


def test_stage_and_channel_are_closed_sets(session: Session, user_id: uuid.UUID) -> None:
    opportunity = make_opportunity(session, user_id)
    session.commit()

    inserts = (
        "INSERT INTO applications (id, user_id, opportunity_id, applied_at, stage) "
        "VALUES (:id, :user, :opp, now(), :value)",
        "INSERT INTO applications (id, user_id, opportunity_id, applied_at, channel) "
        "VALUES (:id, :user, :opp, now(), :value)",
    )
    for statement, value in zip(inserts, ("ghosted", "carrier_pigeon"), strict=True):
        with pytest.raises(IntegrityError):
            session.execute(
                text(statement),
                {"id": uuid.uuid4(), "user": user_id, "opp": opportunity.id, "value": value},
            )
        session.rollback()


@pytest.mark.parametrize("stage", [stage.value for stage in ApplicationStage])
def test_is_terminal_must_match_the_stage(session: Session, user_id: uuid.UUID, stage: str) -> None:
    opportunity = make_opportunity(session, user_id)
    session.commit()
    terminal = stage in {"rejected", "withdrawn", "accepted", "declined", "no_response"}

    for flag in (terminal, not terminal):
        statement = text(
            "INSERT INTO applications (id, user_id, opportunity_id, applied_at, stage, "
            "is_terminal) VALUES (:id, :user, :opp, now(), :stage, :flag)"
        )
        params = {
            "id": uuid.uuid4(),
            "user": user_id,
            "opp": opportunity.id,
            "stage": stage,
            "flag": flag,
        }
        if flag == terminal:
            session.execute(statement, params)
            session.rollback()
        else:
            with pytest.raises(IntegrityError, match="terminal_matches_stage"):
                session.execute(statement, params)
            session.rollback()


def test_only_one_non_terminal_application_per_opportunity(
    session: Session, user_id: uuid.UUID
) -> None:
    opportunity = make_opportunity(session, user_id)
    other = make_opportunity(session, user_id)
    first = make_application(session, user_id, opportunity.id)
    session.commit()

    with pytest.raises(IntegrityError, match="uq_applications_open_per_opportunity"):
        make_application(session, user_id, opportunity.id)
    session.rollback()
    make_application(session, user_id, other.id)
    session.commit()

    session.execute(
        text("UPDATE applications SET stage = 'rejected', is_terminal = true WHERE id = :id"),
        {"id": first.id},
    )
    make_application(session, user_id, opportunity.id)
    session.commit()
    count: int = session.execute(
        text("SELECT count(*) FROM applications WHERE opportunity_id = :id"), {"id": opportunity.id}
    ).scalar_one()
    assert count == 2


def test_a_cross_user_reference_cannot_be_written(session: Session, user_id: uuid.UUID) -> None:
    other = make_user(session)
    session.commit()
    foreign_opportunity = make_opportunity(session, other.id)
    foreign_artifact = make_artifact(session, other.id)
    foreign_lane = ResumeLane(user_id=other.id, name="foreign")
    session.add(foreign_lane)
    session.flush()
    foreign_resume = Resume(user_id=other.id, artifact_id=foreign_artifact.id, label="foreign")
    session.add(foreign_resume)
    session.commit()
    mine = make_opportunity(session, user_id)
    session.commit()

    with pytest.raises(IntegrityError):
        make_application(session, user_id, foreign_opportunity.id)
    session.rollback()
    with pytest.raises(IntegrityError):
        make_application(session, user_id, mine.id, resume_id=foreign_resume.id)
    session.rollback()
    with pytest.raises(IntegrityError):
        make_application(session, user_id, mine.id, lane_id=foreign_lane.id)
    session.rollback()


def test_the_app_role_can_insert_update_and_select_but_not_delete(
    session: Session, user_id: uuid.UUID
) -> None:
    opportunity = make_opportunity(session, user_id)
    row = make_application(session, user_id, opportunity.id)
    session.commit()

    row.stage = ApplicationStage.ASSESSMENT
    session.commit()

    assert_denied(session, "DELETE FROM applications")
    assert_denied(session, "TRUNCATE applications")


def test_deleting_the_user_cascades_to_applications(
    session: Session, owner_session: Session, user_id: uuid.UUID
) -> None:
    opportunity = make_opportunity(session, user_id)
    make_application(session, user_id, opportunity.id)
    session.commit()

    owner_session.execute(
        text("UPDATE users SET status = 'deletion_requested' WHERE id = :id"), {"id": user_id}
    )
    owner_session.execute(text("SELECT public.delete_user_account(:id)"), {"id": user_id})
    owner_session.commit()

    remaining: int = owner_session.execute(
        text("SELECT count(*) FROM applications WHERE user_id = :id"), {"id": user_id}
    ).scalar_one()
    assert remaining == 0
