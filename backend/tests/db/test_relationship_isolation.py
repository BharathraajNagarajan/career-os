from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.application_helpers import applied
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import (
    ACTIONS,
    CONTACTS,
    INTERACTIONS,
    RULES,
    create_action,
    create_company,
    create_contact,
    create_interaction,
    get_contact,
    merge,
)
from tests.db.opportunity_helpers import scalar
from tests.db.resume_helpers import create_lane

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def count(owner: Session, table: str) -> int:
    return int(scalar(owner, f"SELECT count(*) FROM {table}"))  # noqa: S608


def test_interactions_reject_foreign_body_references(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    mine = create_contact(persona)
    theirs = create_contact(other, "Sam Example")
    opportunity, application = applied(other, "foreign body refs")

    attempts: list[dict[str, Any]] = [
        {"contact_id": theirs["id"]},
        {"contact_id": mine["id"], "opportunity_id": opportunity["id"]},
        {"contact_id": mine["id"], "application_id": application["id"]},
    ]
    for attempt in attempts:
        contact_id = attempt.pop("contact_id")
        assert create_interaction(persona, contact_id, **attempt).status_code == 404

    assert count(owner_session, "interactions") == 0
    assert persona.request("GET", INTERACTIONS, params={"contact_id": theirs["id"]}).json() == []


def test_actions_reject_foreign_body_references(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    theirs = create_contact(other, "Sam Example")
    opportunity, application = applied(other, "foreign action refs")

    for extra in (
        {"contact_id": theirs["id"]},
        {"opportunity_id": opportunity["id"]},
        {"application_id": application["id"]},
    ):
        assert create_action(persona, **extra).status_code == 404

    assert count(owner_session, "recruiting_actions") == 0
    assert persona.request("GET", ACTIONS, params={"contact_id": theirs["id"]}).json() == []


def test_rules_reject_foreign_scope_targets(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    company = create_company(other, "Other Corp")
    lane = create_lane(other, "Other lane")

    by_company = persona.request(
        "POST",
        RULES,
        json={
            "scope": "company",
            "company_id": company["id"],
            "statement": "x",
            "rule_type": "preference",
        },
    )
    by_lane = persona.request(
        "POST",
        RULES,
        json={"scope": "lane", "lane_id": lane["id"], "statement": "x", "rule_type": "preference"},
    )

    assert (by_company.status_code, by_lane.status_code) == (404, 404)
    assert count(owner_session, "strategy_rules") == 0


def test_merge_with_a_foreign_merged_id_changes_nothing(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    mine = create_contact(persona, "Alex Example", ["alex@example.test"])
    theirs = create_contact(other, "Sam Example", ["sam@example.test"])

    assert merge(persona, mine, theirs).status_code == 404

    assert count(owner_session, "contacts") == 2
    assert [item["address"] for item in get_contact(persona, mine["id"])["emails"]] == [
        "alex@example.test"
    ]
    assert get_contact(other, theirs["id"])["full_name"] == "Sam Example"
    assert persona.request("GET", f"{CONTACTS}/{theirs['id']}").status_code == 404
