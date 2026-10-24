import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.db.contact_helpers import insert_row
from tests.db.factories import make_user
from tests.db.test_opportunity_schema import make_artifact
from tests.db.test_roles import assert_denied

pytestmark = pytest.mark.db


@pytest.fixture
def user_id(session: Session) -> uuid.UUID:
    user = make_user(session)
    session.commit()
    return user.id


def skill(session: Session, user_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    key = uuid.uuid4().hex
    values: dict[str, Any] = {
        "canonical_name": "Widgets",
        "normalized_key": key,
        "origin": "user",
        **extra,
    }
    return insert_row(session, "skills", user_id=user_id, **values)


def claim(session: Session, user_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "statement": "Built sample widgets",
        "evidence_class": "project",
        "origin": "user",
        **extra,
    }
    return insert_row(session, "claims", user_id=user_id, **values)


def source(session: Session, user_id: uuid.UUID, claim_id: uuid.UUID, **extra: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "source_type": "user_assertion",
        "assertion_text": "I built them",
        **extra,
    }
    return insert_row(session, "evidence_sources", user_id=user_id, claim_id=claim_id, **values)


def rejected(session: Session, write: Callable[[], object], match: str | None = None) -> None:
    with pytest.raises(IntegrityError, match=match):
        write()
    session.rollback()


def test_skill_defaults_and_closed_enums(session: Session, user_id: uuid.UUID) -> None:
    skill_id = skill(session, user_id)
    session.commit()

    row = session.execute(
        text(
            "SELECT confirmation_status, user_marked_gap, user_note, aliases, state_version, "
            "merged_into_skill_id FROM skills WHERE id = :id"
        ),
        {"id": skill_id},
    ).one()
    assert tuple(row) == ("confirmed", False, "", [], 1, None)
    rejected(session, lambda: skill(session, user_id, origin="gmail"), "ck_skills_origin")
    rejected(
        session,
        lambda: skill(session, user_id, confirmation_status="merged"),
        "ck_skills_confirmation_status",
    )
    rejected(session, lambda: skill(session, user_id, canonical_name=""), "canonical_name_length")
    rejected(session, lambda: skill(session, user_id, normalized_key=""), "normalized_key")


def test_skill_names_are_unique_per_user_until_merged(session: Session, user_id: uuid.UUID) -> None:
    first = skill(session, user_id, normalized_key="widgets")
    other = make_user(session).id
    skill(session, other, normalized_key="widgets")
    session.commit()

    rejected(
        session,
        lambda: skill(session, user_id, normalized_key="widgets"),
        "uq_skills_user_id_normalized_key",
    )
    survivor = skill(session, user_id, normalized_key="gadgets")
    session.execute(
        text("UPDATE skills SET merged_into_skill_id = :survivor WHERE id = :id"),
        {"survivor": survivor, "id": first},
    )
    skill(session, user_id, normalized_key="widgets")
    session.commit()


def test_skill_merge_and_gap_constraints(session: Session, user_id: uuid.UUID) -> None:
    first = skill(session, user_id)
    second = skill(session, user_id)
    session.commit()

    rejected(
        session,
        lambda: session.execute(
            text("UPDATE skills SET merged_into_skill_id = id WHERE id = :id"), {"id": first}
        ),
        "merge_not_self",
    )
    rejected(
        session,
        lambda: session.execute(
            text("UPDATE skills SET gap_note = 'no' WHERE id = :id"), {"id": first}
        ),
        "gap_note_needs_gap",
    )
    rejected(
        session,
        lambda: session.execute(
            text(
                "UPDATE skills SET merged_into_skill_id = :second, user_marked_gap = true "
                "WHERE id = :id"
            ),
            {"second": second, "id": first},
        ),
        "merged_has_no_gap",
    )
    rejected(
        session,
        lambda: session.execute(
            text("UPDATE skills SET aliases = ARRAY(SELECT 'a' || g FROM generate_series(1, 21) g)")
        ),
        "aliases_count",
    )


def test_skill_cannot_redirect_to_another_users_skill(session: Session, user_id: uuid.UUID) -> None:
    mine = skill(session, user_id)
    foreign = skill(session, make_user(session).id)
    session.commit()

    rejected(
        session,
        lambda: session.execute(
            text("UPDATE skills SET merged_into_skill_id = :foreign WHERE id = :id"),
            {"foreign": foreign, "id": mine},
        ),
        "fk_skills_user_id_merged_into_skill_id_skills",
    )


def test_claim_class_and_engagement_type_rules(session: Session, user_id: uuid.UUID) -> None:
    claim(session, user_id)
    claim(session, user_id, evidence_class="professional", engagement_type="internship")
    session.commit()

    rejected(
        session,
        lambda: claim(session, user_id, evidence_class="professional"),
        "engagement_type_only_professional",
    )
    rejected(
        session,
        lambda: claim(session, user_id, evidence_class="project", engagement_type="full_time"),
        "engagement_type_only_professional",
    )
    rejected(
        session,
        lambda: claim(session, user_id, evidence_class="employment"),
        "ck_claims_evidence_class",
    )
    rejected(
        session,
        lambda: claim(session, user_id, evidence_class="professional", engagement_type="volunteer"),
        "ck_claims_engagement_type",
    )
    rejected(
        session,
        lambda: claim(session, user_id, confirmation_status="pending"),
        "ck_claims_confirmation_status",
    )
    rejected(session, lambda: claim(session, user_id, origin="gmail"), "ck_claims_origin")
    rejected(session, lambda: claim(session, user_id, statement=""), "statement_length")
    rejected(
        session,
        lambda: claim(session, user_id, start_date="2026-02-01", end_date="2026-01-01"),
        "dates_ordered",
    )


def test_evidence_source_shape_depends_on_its_type(session: Session, user_id: uuid.UUID) -> None:
    claim_id = claim(session, user_id)
    artifact = make_artifact(session, user_id)
    source(session, user_id, claim_id)
    source(
        session,
        user_id,
        claim_id,
        source_type="resume",
        artifact_id=artifact.id,
        assertion_text=None,
    )
    source(
        session,
        user_id,
        claim_id,
        source_type="project_url",
        url="https://example.test/p",
        assertion_text=None,
    )
    session.commit()

    rejected(
        session,
        lambda: source(session, user_id, claim_id, source_type="resume", assertion_text=None),
        "artifact_only_for_file_sources",
    )
    rejected(
        session,
        lambda: source(session, user_id, claim_id, artifact_id=artifact.id),
        "artifact_only_for_file_sources",
    )
    rejected(
        session,
        lambda: source(session, user_id, claim_id, source_type="project_url", assertion_text=None),
        "url_only_for_project_url",
    )
    rejected(
        session,
        lambda: source(session, user_id, claim_id, assertion_text=None),
        "assertion_only_for_user_assertion",
    )
    rejected(
        session,
        lambda: source(session, user_id, claim_id, source_type="email", assertion_text=None),
        "ck_evidence_sources_source_type",
    )
    rejected(
        session,
        lambda: source(
            session,
            user_id,
            claim_id,
            source_type="project_url",
            url="https://example.test/p",
            assertion_text=None,
            message_id=uuid.uuid4(),
        ),
        "message_scope",
    )


def test_composite_foreign_keys_block_cross_user_references(
    session: Session, user_id: uuid.UUID
) -> None:
    other = make_user(session).id
    foreign_claim = claim(session, other)
    foreign_skill = skill(session, other)
    foreign_artifact = make_artifact(session, other)
    mine = claim(session, user_id)
    my_skill = skill(session, user_id)
    session.commit()

    rejected(session, lambda: source(session, user_id, foreign_claim), "fk_evidence_sources")
    rejected(
        session,
        lambda: source(
            session,
            user_id,
            mine,
            source_type="artifact",
            artifact_id=foreign_artifact.id,
            assertion_text=None,
        ),
        "fk_evidence_sources_user_id_artifact_id_artifacts",
    )
    rejected(
        session,
        lambda: insert_row(
            session, "claim_skills", user_id=user_id, claim_id=foreign_claim, skill_id=my_skill
        ),
        "fk_claim_skills_user_id_claim_id_claims",
    )
    rejected(
        session,
        lambda: insert_row(
            session, "claim_skills", user_id=user_id, claim_id=mine, skill_id=foreign_skill
        ),
        "fk_claim_skills_user_id_skill_id_skills",
    )


def test_a_claim_links_to_a_skill_once(session: Session, user_id: uuid.UUID) -> None:
    claim_id = claim(session, user_id)
    skill_id = skill(session, user_id)
    insert_row(session, "claim_skills", user_id=user_id, claim_id=claim_id, skill_id=skill_id)
    session.commit()

    rejected(
        session,
        lambda: insert_row(
            session, "claim_skills", user_id=user_id, claim_id=claim_id, skill_id=skill_id
        ),
        "uq_claim_skills_user_id_claim_id_skill_id",
    )


def test_grants_keep_provenance_and_sources_immutable(session: Session, user_id: uuid.UUID) -> None:
    claim_id = claim(session, user_id)
    skill_id = skill(session, user_id)
    source_id = source(session, user_id, claim_id)
    link_id = insert_row(
        session, "claim_skills", user_id=user_id, claim_id=claim_id, skill_id=skill_id
    )
    session.commit()
    ids = {
        "claims": claim_id,
        "skills": skill_id,
        "evidence_sources": source_id,
        "claim_skills": link_id,
    }

    allowed = [
        "UPDATE claims SET statement = 'edited', evidence_class = 'learning', "
        "engagement_type = NULL, confirmation_status = 'rejected', start_date = NULL, "
        "end_date = NULL, organization_label = NULL, state_version = 2, updated_at = now() "
        "WHERE id = :claims",
        "UPDATE skills SET canonical_name = 'New', normalized_key = 'new', aliases = '{x}', "
        "confirmation_status = 'rejected', user_marked_gap = true, gap_note = 'n', "
        "user_note = 'n', merged_into_skill_id = NULL, state_version = 2, updated_at = now() "
        "WHERE id = :skills",
        "UPDATE claim_skills SET skill_id = :skills WHERE id = :claim_skills",
    ]
    for statement in allowed:
        session.execute(text(statement), ids)
    session.commit()

    denied = [
        "UPDATE claims SET origin = 'user'",
        "UPDATE claims SET llm_run_id = NULL",
        "UPDATE claims SET created_at = now()",
        "UPDATE claims SET user_id = user_id",
        "UPDATE skills SET origin = 'user'",
        "UPDATE skills SET llm_run_id = NULL",
        "UPDATE skills SET created_at = now()",
        "UPDATE evidence_sources SET assertion_text = 'changed'",
        "UPDATE evidence_sources SET claim_id = claim_id",
        "UPDATE claim_skills SET claim_id = claim_id",
        "DELETE FROM claims",
        "DELETE FROM skills",
        "DELETE FROM evidence_sources",
    ]
    for statement in denied:
        assert_denied(session, statement)


def test_only_claim_skill_links_can_be_deleted(session: Session, user_id: uuid.UUID) -> None:
    claim_id = claim(session, user_id)
    skill_id = skill(session, user_id)
    link_id = insert_row(
        session, "claim_skills", user_id=user_id, claim_id=claim_id, skill_id=skill_id
    )
    session.commit()

    session.execute(text("DELETE FROM claim_skills WHERE id = :id"), {"id": link_id})
    session.commit()

    count = session.execute(text("SELECT count(*) FROM claim_skills")).scalar_one()
    assert count == 0


def test_account_deletion_removes_evidence_rows(
    session: Session, owner_session: Session, user_id: uuid.UUID
) -> None:
    claim_id = claim(session, user_id)
    skill_id = skill(session, user_id)
    source(session, user_id, claim_id)
    insert_row(session, "claim_skills", user_id=user_id, claim_id=claim_id, skill_id=skill_id)
    session.commit()

    owner_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    owner_session.commit()

    for table in ("claims", "skills", "evidence_sources", "claim_skills"):
        count = owner_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0, table
