from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.contact_helpers import RULES, body_of, create_company
from tests.db.opportunity_helpers import scalar
from tests.db.resume_helpers import create_lane

pytestmark = pytest.mark.db


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def make_rule(persona: Persona, **extra: Any) -> Any:
    payload = {"scope": "global", "statement": "No more than two applications a week", **extra}
    payload.setdefault("rule_type", "constraint")
    return persona.request("POST", RULES, json=payload)


def test_a_global_rule_is_stored_with_defaults(persona: Persona) -> None:
    rule = body_of(make_rule(persona, statement="  Prefer remote roles \n"), 201)

    assert rule["scope"] == "global"
    assert rule["company_id"] is None
    assert rule["lane_id"] is None
    assert rule["statement"] == "Prefer remote roles"
    assert rule["active"] is True
    assert rule["condition"] is None


def test_company_and_lane_scoped_rules_carry_their_target(persona: Persona) -> None:
    company = create_company(persona)
    lane = create_lane(persona, "Platform")

    by_company = body_of(make_rule(persona, scope="company", company_id=company["id"]), 201)
    by_lane = body_of(
        make_rule(persona, scope="lane", lane_id=lane["id"], rule_type="preference"), 201
    )

    assert (by_company["company_id"], by_company["lane_id"]) == (company["id"], None)
    assert (by_lane["company_id"], by_lane["lane_id"]) == (None, lane["id"])
    listed = persona.request("GET", RULES, params={"scope": "company"}).json()
    assert [item["id"] for item in listed] == [by_company["id"]]


@pytest.mark.parametrize(
    "extra",
    [
        {"scope": "company"},
        {"scope": "lane"},
        {"scope": "global", "company_id": "00000000-0000-4000-8000-000000000001"},
        {"scope": "global", "lane_id": "00000000-0000-4000-8000-000000000001"},
        {
            "scope": "company",
            "company_id": "00000000-0000-4000-8000-000000000001",
            "lane_id": "00000000-0000-4000-8000-000000000002",
        },
        {"scope": "team"},
        {"rule_type": "wish"},
        {"statement": "   "},
        {"statement": "x" * 1001},
        {"condition": {"schema_version": 1, "kind": "application_cooldown", "days": 0}},
        {"condition": {"schema_version": 1, "kind": "mystery", "days": 3}},
        {"condition": {"schema_version": 2, "kind": "application_cooldown", "days": 3}},
        {"unknown": True},
    ],
)
def test_invalid_rules_are_rejected(persona: Persona, extra: dict[str, Any]) -> None:
    assert make_rule(persona, **extra).status_code == 422


def test_scope_targets_are_resolved_as_the_callers(
    persona: Persona, other: Persona, owner_session: Session
) -> None:
    foreign_company = create_company(other, "Other Corp")
    foreign_lane = create_lane(other, "Other lane")

    company = make_rule(persona, scope="company", company_id=foreign_company["id"])
    lane = make_rule(persona, scope="lane", lane_id=foreign_lane["id"])

    assert (company.status_code, lane.status_code) == (404, 404)
    assert scalar(owner_session, "SELECT count(*) FROM strategy_rules") == 0


def test_a_cooldown_keeps_its_typed_condition(persona: Persona) -> None:
    condition = {"schema_version": 1, "kind": "outreach_cooldown", "days": 14}

    rule = body_of(make_rule(persona, rule_type="cooldown", condition=condition), 201)

    assert rule["condition"] == condition
    cleared = body_of(persona.request("PATCH", f"{RULES}/{rule['id']}", json={"condition": None}))
    assert cleared["condition"] is None


def test_patch_edits_statement_type_and_enabled_flag(persona: Persona) -> None:
    rule = body_of(make_rule(persona), 201)

    edited = body_of(
        persona.request(
            "PATCH",
            f"{RULES}/{rule['id']}",
            json={"statement": "Wait a week", "rule_type": "cooldown", "active": False},
        )
    )

    assert (edited["statement"], edited["rule_type"], edited["active"]) == (
        "Wait a week",
        "cooldown",
        False,
    )
    assert edited["scope"] == "global"
    assert (
        persona.request("PATCH", f"{RULES}/{rule['id']}", json={"scope": "lane"}).status_code == 422
    )
    inactive = persona.request("GET", RULES, params={"active": "false"}).json()
    assert [item["id"] for item in inactive] == [rule["id"]]


def test_delete_removes_only_that_rule(persona: Persona) -> None:
    first = body_of(make_rule(persona), 201)
    second = body_of(make_rule(persona, statement="Second rule"), 201)

    assert persona.request("DELETE", f"{RULES}/{first['id']}").status_code == 204
    assert persona.request("DELETE", f"{RULES}/{first['id']}").status_code == 404

    listed = persona.request("GET", RULES).json()
    assert [item["id"] for item in listed] == [second["id"]]
