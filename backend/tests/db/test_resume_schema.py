import hashlib
import uuid
from typing import Any

import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import (
    Artifact,
    ArtifactKind,
    ExtractionStatus,
    LaneStatus,
    Profile,
    Resume,
    ResumeLane,
    User,
    UserStatus,
)
from tests.db.factories import make_user

pytestmark = pytest.mark.db

EMPTY_PAYLOAD: dict[str, Any] = {"schema_version": 1}


def make_artifact(session: Session, user_id: uuid.UUID, tag: str = "a") -> Artifact:
    artifact = Artifact(
        user_id=user_id,
        kind=ArtifactKind.RESUME_FILE,
        storage_key=f"users/{user_id}/artifacts/{new_id()}",
        sha256=hashlib.sha256(tag.encode()).digest(),
        mime_type="application/pdf",
        byte_size=10,
        original_filename=f"{tag}.pdf",
    )
    session.add(artifact)
    session.flush()
    return artifact


def make_resume(
    session: Session, user_id: uuid.UUID, tag: str = "a", lane_id: uuid.UUID | None = None
) -> Resume:
    artifact = make_artifact(session, user_id, tag)
    resume = Resume(user_id=user_id, artifact_id=artifact.id, label=tag, lane_id=lane_id)
    session.add(resume)
    session.flush()
    return resume


def make_lane(session: Session, user_id: uuid.UUID, name: str = "Lane") -> ResumeLane:
    lane = ResumeLane(user_id=user_id, name=name)
    session.add(lane)
    session.flush()
    return lane


def assert_denied(session: Session, statement: str) -> None:
    with pytest.raises(ProgrammingError) as error:
        session.execute(text(statement))
    assert isinstance(error.value.orig, psycopg.errors.InsufficientPrivilege)
    session.rollback()


def test_artifact_content_columns_are_immutable_by_privilege(session: Session) -> None:
    user = make_user(session)
    make_artifact(session, user.id)
    session.commit()

    for column, value in (
        ("storage_key", "'elsewhere'"),
        ("sha256", "'\\x00'::bytea"),
        ("byte_size", "1"),
        ("mime_type", "'text/plain'"),
        ("original_filename", "'renamed.pdf'"),
        ("kind", "'reference'"),
        ("user_id", f"'{new_id()}'"),
    ):
        assert_denied(session, f"UPDATE artifacts SET {column} = {value}")  # noqa: S608


def test_artifact_extraction_columns_can_be_updated(session: Session) -> None:
    user = make_user(session)
    artifact = make_artifact(session, user.id)
    session.commit()

    artifact.extracted_text = "synthetic text"
    artifact.extraction_status = ExtractionStatus.SUCCEEDED
    artifact.extraction_error_code = None
    session.commit()

    stored: str = session.execute(text("SELECT extracted_text FROM artifacts")).scalar_one()
    assert stored == "synthetic text"


@pytest.mark.parametrize("table", ["artifacts", "resumes", "resume_lanes", "profiles"])
def test_app_role_cannot_delete_or_truncate_the_new_tables(session: Session, table: str) -> None:
    assert_denied(session, f"DELETE FROM {table}")  # noqa: S608
    assert_denied(session, f"TRUNCATE {table}")


def test_profile_has_one_row_per_user(session: Session) -> None:
    user = make_user(session)
    for _ in range(2):
        session.add(
            Profile(
                user_id=user.id,
                work_authorization=EMPTY_PAYLOAD,
                target_roles=EMPTY_PAYLOAD,
                communication_preferences=EMPTY_PAYLOAD,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_content_is_unique_per_user_and_kind(session: Session) -> None:
    first, second = make_user(session), make_user(session)
    make_artifact(session, first.id, "same")
    make_artifact(session, second.id, "same")
    session.commit()

    with pytest.raises(IntegrityError):
        make_artifact(session, first.id, "same")
    session.rollback()


def test_hash_must_be_32_bytes(session: Session) -> None:
    user = make_user(session)
    session.add(
        Artifact(
            user_id=user.id,
            kind=ArtifactKind.RESUME_FILE,
            storage_key="k",
            sha256=b"short",
            mime_type="application/pdf",
            byte_size=1,
            original_filename="x.pdf",
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_other_users_rows_cannot_be_referenced(session: Session) -> None:
    owner, intruder = make_user(session), make_user(session)
    foreign_lane = make_lane(session, owner.id)
    foreign_artifact = make_artifact(session, owner.id)
    foreign_resume = make_resume(session, owner.id, "owned")
    session.commit()

    session.add(Resume(user_id=intruder.id, artifact_id=foreign_artifact.id, label="x"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    mine = make_artifact(session, intruder.id, "mine")
    session.add(
        Resume(user_id=intruder.id, artifact_id=mine.id, label="x", lane_id=foreign_lane.id)
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    lane = make_lane(session, intruder.id, "Mine")
    lane.default_resume_id = foreign_resume.id
    with pytest.raises(IntegrityError):
        session.flush()


def test_active_lane_names_are_unique_ignoring_case_but_archived_ones_are_free(
    session: Session,
) -> None:
    user = make_user(session)
    other = make_user(session)
    make_lane(session, user.id, "Platform")
    make_lane(session, other.id, "platform")
    session.commit()

    session.add(ResumeLane(user_id=user.id, name="PLATFORM"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    archived = make_lane(session, user.id, "Old")
    archived.status = LaneStatus.ARCHIVED
    session.flush()
    make_lane(session, user.id, "old")


def test_account_deletion_cascades_through_the_circular_foreign_keys(
    session: Session, owner_session: Session
) -> None:
    user = make_user(session)
    lane = make_lane(session, user.id)
    resume = make_resume(session, user.id, lane_id=lane.id)
    lane.default_resume_id = resume.id
    session.add(
        Profile(
            user_id=user.id,
            work_authorization=EMPTY_PAYLOAD,
            target_roles=EMPTY_PAYLOAD,
            communication_preferences=EMPTY_PAYLOAD,
        )
    )
    session.get_one(User, user.id).status = UserStatus.DELETION_REQUESTED
    session.commit()

    deleted = session.execute(text("SELECT public.delete_user_account(:id)"), {"id": user.id})
    session.commit()

    assert deleted.scalar_one() is True
    for table in ("users", "profiles", "artifacts", "resumes", "resume_lanes"):
        remaining: int = owner_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert remaining == 0, table
        owner_session.rollback()


def test_circular_foreign_keys_use_no_action(owner_session: Session) -> None:
    rows = owner_session.execute(
        text(
            "SELECT conname, confdeltype FROM pg_constraint "
            "WHERE conname IN ("
            "'fk_resumes_user_id_artifact_id_artifacts', "
            "'fk_resumes_user_id_lane_id_resume_lanes', "
            "'fk_resume_lanes_user_id_default_resume_id_resumes')"
        )
    ).all()

    assert len(rows) == 3
    assert {row.confdeltype for row in rows} == {"a"}
