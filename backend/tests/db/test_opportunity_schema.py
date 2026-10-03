import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import (
    Artifact,
    ArtifactKind,
    Company,
    CompanyOrigin,
    ExtractionStatus,
    Opportunity,
    OpportunitySource,
    Qualification,
    QualificationCategory,
    QualificationKind,
    QualificationOrigin,
)
from tests.db.factories import make_user
from tests.db.test_roles import assert_denied

pytestmark = pytest.mark.db

EMPTY_LOCATIONS: dict[str, Any] = {"schema_version": 1, "items": []}


def make_company(session: Session, user_id: uuid.UUID, name: str = "example") -> Company:
    company = Company(
        user_id=user_id, name=name, normalized_name=name.lower(), origin=CompanyOrigin.USER
    )
    session.add(company)
    session.flush()
    return company


def make_artifact(session: Session, user_id: uuid.UUID) -> Artifact:
    digest = hashlib.sha256(new_id().bytes).digest()
    artifact = Artifact(
        user_id=user_id,
        kind=ArtifactKind.JD_SNAPSHOT,
        storage_key=f"users/{user_id}/artifacts/{new_id()}",
        sha256=digest,
        mime_type="text/plain",
        byte_size=3,
        original_filename="jd.txt",
        extracted_text="abc",
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    session.add(artifact)
    session.flush()
    return artifact


def make_opportunity(
    session: Session,
    user_id: uuid.UUID,
    *,
    company_id: uuid.UUID | None = None,
    external_job_id: str | None = None,
    artifact_id: uuid.UUID | None = None,
    **extra: Any,
) -> Opportunity:
    opportunity = Opportunity(
        user_id=user_id,
        company_id=company_id,
        external_job_id=external_job_id,
        jd_artifact_id=artifact_id or make_artifact(session, user_id).id,
        source=OpportunitySource.MANUAL_PASTE,
        locations=EMPTY_LOCATIONS,
        content_updated_at=datetime.now(UTC),
        discovered_at=datetime.now(UTC),
        **extra,
    )
    session.add(opportunity)
    session.flush()
    return opportunity


def make_qualification(
    session: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> Qualification:
    row = Qualification(
        user_id=user_id,
        opportunity_id=opportunity_id,
        kind=QualificationKind.MINIMUM,
        ordinal=0,
        text_verbatim="Proficiency in Python",
        category=QualificationCategory.SKILL,
        origin=QualificationOrigin.USER,
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
    company = make_company(session, user_id)
    opportunity = make_opportunity(session, user_id, company_id=company.id)
    session.commit()
    session.refresh(company)
    session.refresh(opportunity)

    assert company.strategic_priority.value == "normal"
    assert company.aliases == []
    assert company.domains == []
    assert opportunity.status.value == "new"
    assert opportunity.priority.value == "normal"
    assert opportunity.extraction_status.value == "pending"
    assert opportunity.workplace_type.value == "unspecified"
    assert opportunity.state_version == 1
    assert opportunity.latest_evaluation_id is None


def test_company_names_are_unique_per_user_after_normalization(
    session: Session, user_id: uuid.UUID
) -> None:
    make_company(session, user_id, "example")
    session.commit()

    with pytest.raises(IntegrityError):
        make_company(session, user_id, "example")
    session.rollback()
    other = make_user(session)
    session.commit()
    make_company(session, other.id, "example")
    session.commit()


def test_a_cross_user_reference_cannot_be_written(session: Session, user_id: uuid.UUID) -> None:
    other = make_user(session)
    session.commit()
    foreign_company = make_company(session, other.id, "foreign")
    session.commit()

    with pytest.raises(IntegrityError):
        make_opportunity(session, user_id, company_id=foreign_company.id)
    session.rollback()
    mine = make_opportunity(session, user_id)
    session.commit()
    foreign = make_opportunity(session, other.id)
    session.commit()
    with pytest.raises(IntegrityError):
        make_qualification(session, user_id, foreign.id)
    session.rollback()
    with pytest.raises(IntegrityError):
        make_opportunity(session, user_id, artifact_id=make_artifact(session, other.id).id)
    session.rollback()
    assert mine.id is not None


def test_partial_unique_index_on_company_and_job_id(session: Session, user_id: uuid.UUID) -> None:
    company = make_company(session, user_id)
    other_company = make_company(session, user_id, "other")
    make_opportunity(session, user_id, company_id=company.id, external_job_id="EX-1")
    session.commit()

    with pytest.raises(IntegrityError):
        make_opportunity(session, user_id, company_id=company.id, external_job_id="EX-1")
    session.rollback()
    make_opportunity(session, user_id, company_id=other_company.id, external_job_id="EX-1")
    make_opportunity(session, user_id, company_id=company.id, external_job_id="EX-2")
    make_opportunity(session, user_id, company_id=company.id, external_job_id=None)
    make_opportunity(session, user_id, company_id=company.id, external_job_id=None)
    make_opportunity(session, user_id, company_id=None, external_job_id="EX-1")
    make_opportunity(session, user_id, company_id=None, external_job_id="EX-1")
    session.commit()


def test_one_opportunity_per_jd_artifact(session: Session, user_id: uuid.UUID) -> None:
    artifact = make_artifact(session, user_id)
    make_opportunity(session, user_id, artifact_id=artifact.id)
    session.commit()

    with pytest.raises(IntegrityError):
        make_opportunity(session, user_id, artifact_id=artifact.id)
    session.rollback()


def test_extraction_error_code_exists_exactly_when_extraction_failed(
    session: Session, user_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError):
        make_opportunity(
            session, user_id, extraction_status=ExtractionStatus.FAILED, extraction_error_code=None
        )
    session.rollback()
    with pytest.raises(IntegrityError):
        make_opportunity(
            session,
            user_id,
            extraction_status=ExtractionStatus.PENDING,
            extraction_error_code="llm_output_invalid",
        )
    session.rollback()
    make_opportunity(
        session,
        user_id,
        extraction_status=ExtractionStatus.FAILED,
        extraction_error_code="llm_output_invalid",
    )
    session.commit()


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'archived'",
        "priority = 'urgent'",
        "workplace_type = 'office'",
        "source = 'url_fetch'",
        "extraction_status = 'done'",
        "locations = '[]'::jsonb",
    ],
)
def test_opportunity_checks_reject_bad_values(
    session: Session, owner_session: Session, user_id: uuid.UUID, assignment: str
) -> None:
    make_opportunity(session, user_id)
    session.commit()

    with pytest.raises(IntegrityError):
        owner_session.execute(text("UPDATE opportunities SET " + assignment))  # noqa: S608
    owner_session.rollback()


@pytest.mark.parametrize(
    "assignment",
    [
        "kind = 'required'",
        "category = 'perk'",
        "origin = 'chat'",
        "min_years = 51",
        "min_years = -1",
        "ordinal = -1",
        "text_verbatim = ''",
    ],
)
def test_qualification_checks_reject_bad_values(
    session: Session, owner_session: Session, user_id: uuid.UUID, assignment: str
) -> None:
    opportunity = make_opportunity(session, user_id)
    make_qualification(session, user_id, opportunity.id)
    session.commit()

    with pytest.raises(IntegrityError):
        owner_session.execute(text("UPDATE qualifications SET " + assignment))  # noqa: S608
    owner_session.rollback()


def test_verbatim_text_is_immutable_by_privilege(session: Session, user_id: uuid.UUID) -> None:
    opportunity = make_opportunity(session, user_id)
    make_qualification(session, user_id, opportunity.id)
    session.commit()

    assert_denied(session, "UPDATE qualifications SET text_verbatim = 'edited'")
    assert_denied(session, "UPDATE qualifications SET origin = 'extracted'")
    assert_denied(session, "UPDATE qualifications SET opportunity_id = gen_random_uuid()")
    assert_denied(session, "UPDATE qualifications SET llm_run_id = NULL")
    assert_denied(session, "UPDATE qualifications SET user_id = gen_random_uuid()")
    assert_denied(session, "UPDATE qualifications SET created_at = now()")


def test_normalized_qualification_columns_can_be_updated_and_rows_deleted(
    session: Session, user_id: uuid.UUID
) -> None:
    opportunity = make_opportunity(session, user_id)
    make_qualification(session, user_id, opportunity.id)
    session.commit()

    session.execute(
        text(
            "UPDATE qualifications SET kind = 'preferred', ordinal = 3, category = 'domain', "
            "skill_keys = ARRAY['a'], min_years = 2, is_hard_constraint = true, "
            "updated_at = now()"
        )
    )
    session.execute(text("DELETE FROM qualifications"))
    session.commit()

    assert session.execute(text("SELECT count(*) FROM qualifications")).scalar_one() == 0


def test_companies_and_opportunities_cannot_be_deleted_by_the_app_role(
    session: Session, user_id: uuid.UUID
) -> None:
    company = make_company(session, user_id)
    make_opportunity(session, user_id, company_id=company.id)
    session.commit()

    assert_denied(session, "DELETE FROM opportunities")
    assert_denied(session, "DELETE FROM companies")
    assert_denied(session, "TRUNCATE opportunities")
    assert_denied(session, "TRUNCATE companies")
    assert_denied(session, "TRUNCATE qualifications")


def test_app_role_can_update_company_and_opportunity_content(
    session: Session, user_id: uuid.UUID
) -> None:
    company = make_company(session, user_id)
    opportunity = make_opportunity(session, user_id, company_id=company.id)
    session.commit()

    company.notes = "edited"
    opportunity.title = "Edited"
    session.commit()
