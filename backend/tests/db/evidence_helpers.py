from typing import Any

import httpx2
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.db.auth_helpers import Persona
from tests.db.contact_helpers import body_of
from tests.db.resume_helpers import upload
from tests.synthetic import synthetic_pdf

SKILLS = "/api/v1/skills"
CLAIMS = "/api/v1/claims"
OWN_WORDS = {"source_type": "user_assertion", "assertion_text": "My own words about this work"}


def create_skill(persona: Persona, name: str = "Widgets", **extra: Any) -> dict[str, Any]:
    return body_of(persona.request("POST", SKILLS, json={"canonical_name": name, **extra}), 201)


def get_skill(persona: Persona, skill_id: str) -> dict[str, Any]:
    return body_of(persona.request("GET", f"{SKILLS}/{skill_id}"))


def create_claim_response(
    persona: Persona,
    statement: str = "Built sample widgets for fictional customers",
    evidence_class: str = "project",
    **extra: Any,
) -> httpx2.Response:
    payload: dict[str, Any] = {
        "statement": statement,
        "evidence_class": evidence_class,
        "sources": [OWN_WORDS],
        **extra,
    }
    return persona.request("POST", CLAIMS, json=payload)


def create_claim(persona: Persona, *skill_ids: str, **extra: Any) -> dict[str, Any]:
    response = create_claim_response(persona, skill_ids=list(skill_ids), **extra)
    return body_of(response, 201)


def professional(
    persona: Persona, *skill_ids: str, engagement: str, **extra: Any
) -> dict[str, Any]:
    return create_claim(
        persona, *skill_ids, evidence_class="professional", engagement_type=engagement, **extra
    )


def get_claim(persona: Persona, claim_id: str) -> dict[str, Any]:
    return body_of(persona.request("GET", f"{CLAIMS}/{claim_id}"))


def reclassify(
    persona: Persona,
    claim: dict[str, Any],
    evidence_class: str,
    engagement_type: str | None = None,
    *,
    confirm: bool = True,
) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{CLAIMS}/{claim['id']}/classification",
        json={
            "expected_state_version": claim["state_version"],
            "evidence_class": evidence_class,
            "engagement_type": engagement_type,
            "confirm_change": confirm,
        },
    )


def mark_gap(persona: Persona, skill: dict[str, Any], note: str | None = None) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{SKILLS}/{skill['id']}/mark-gap",
        json={"expected_state_version": skill["state_version"], "note": note},
    )


def merge_skills(
    persona: Persona, survivor: dict[str, Any], merged: dict[str, Any]
) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{SKILLS}/{survivor['id']}/merge",
        json={
            "merged_id": merged["id"],
            "expected_state_version": survivor["state_version"],
            "expected_merged_state_version": merged["state_version"],
        },
    )


def skill_updated_at(owner: Session, skill_id: str) -> Any:
    owner.rollback()
    return owner.execute(
        text("SELECT updated_at FROM skills WHERE id = :id"), {"id": skill_id}
    ).scalar_one()


def events_of(owner: Session, aggregate_type: str, aggregate_id: str) -> list[str]:
    owner.rollback()
    return [
        row.event_type
        for row in owner.execute(
            text(
                "SELECT event_type FROM domain_events WHERE aggregate_type = :type "
                "AND aggregate_id = :id ORDER BY recorded_at, id"
            ),
            {"type": aggregate_type, "id": aggregate_id},
        )
    ]


def upload_resume(
    persona: Persona, owner: Session, *, tag: str = "a", text_body: str | None = None
) -> dict[str, Any]:
    body = body_of(upload(persona, synthetic_pdf(tag), label=f"Resume {tag}"), 202)
    if text_body is not None:
        owner.rollback()
        owner.execute(
            text(
                "UPDATE artifacts SET extracted_text = :body, extraction_status = 'succeeded' "
                "WHERE id = (SELECT artifact_id FROM resumes WHERE id = :id)"
            ),
            {"body": text_body, "id": body["id"]},
        )
        owner.commit()
    return body
