from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona

pytestmark = pytest.mark.db

BASE: dict[str, Any] = {
    "headline": "Synthetic Engineer",
    "summary": "Sample summary used by tests.",
    "current_location": "Exampleville",
    "relocation_preference": "open",
    "remote_preference": "hybrid",
    "work_authorization": [
        {"country": "us", "status": "Sample status", "sponsorship_needed": False}
    ],
    "target_roles": [{"name": "Platform Engineer", "priority": "high", "notes": "sample"}],
    "communication_preferences": {
        "tone": "direct",
        "length": "short",
        "sign_off": "Regards",
        "avoid": ["jargon"],
    },
}


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


def put(persona: Persona, **changes: Any) -> Any:
    return persona.request("PUT", "/api/v1/profile", json={**BASE, **changes})


def constraints_stamp(owner: Session) -> Any:
    owner.rollback()
    return owner.execute(text("SELECT constraints_updated_at FROM profiles")).scalar_one()


def test_first_read_creates_an_empty_profile_without_career_defaults(
    persona: Persona, owner_session: Session
) -> None:
    body = persona.client.get("/api/v1/profile").json()

    assert body["headline"] is None
    assert body["summary"] is None
    assert body["current_location"] is None
    assert body["relocation_preference"] == "unspecified"
    assert body["remote_preference"] == "no_preference"
    assert body["work_authorization"] == []
    assert body["target_roles"] == []
    assert body["communication_preferences"] == {
        "tone": "",
        "length": "",
        "sign_off": "",
        "avoid": [],
    }
    assert body["constraints_updated_at"]
    owner_session.rollback()
    assert owner_session.execute(text("SELECT count(*) FROM profiles")).scalar_one() == 1


def test_reading_twice_keeps_one_profile(persona: Persona, owner_session: Session) -> None:
    first = persona.client.get("/api/v1/profile").json()
    second = persona.client.get("/api/v1/profile").json()

    assert first == second
    owner_session.rollback()
    assert owner_session.execute(text("SELECT count(*) FROM profiles")).scalar_one() == 1


def test_put_replaces_the_editable_fields(persona: Persona) -> None:
    response = put(persona)

    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "Synthetic Engineer"
    assert body["work_authorization"] == [
        {"country": "US", "status": "Sample status", "sponsorship_needed": False}
    ]
    assert body["target_roles"][0]["name"] == "Platform Engineer"
    assert persona.client.get("/api/v1/profile").json() == body

    cleared = persona.request("PUT", "/api/v1/profile", json={}).json()

    assert cleared["headline"] is None
    assert cleared["target_roles"] == []
    assert cleared["relocation_preference"] == "unspecified"


def test_json_columns_carry_a_schema_version(persona: Persona, owner_session: Session) -> None:
    put(persona)

    owner_session.rollback()
    row = owner_session.execute(
        text("SELECT work_authorization, target_roles, communication_preferences FROM profiles")
    ).one()
    assert row.work_authorization["schema_version"] == 1
    assert row.target_roles["schema_version"] == 1
    assert row.communication_preferences["schema_version"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"relocation_preference": "maybe"},
        {"remote_preference": "sometimes"},
        {"headline": "x" * 201},
        {"summary": "x" * 4001},
        {"work_authorization": [{"country": "USA", "status": "x"}]},
        {"work_authorization": [{"country": "U1", "status": "x"}]},
        {"work_authorization": [{"country": "US", "status": ""}]},
        {"work_authorization": [{"country": "US", "status": "x", "extra": 1}] * 1},
        {"work_authorization": [{"country": "US", "status": "x"}] * 21},
        {"target_roles": [{"name": "x", "priority": "urgent"}]},
        {"target_roles": [{"name": ""}]},
        {"target_roles": [{"name": "x"}] * 21},
        {"communication_preferences": {"tone": "x" * 201}},
        {"communication_preferences": {"avoid": [""]}},
        {"communication_preferences": {"schema_version": 2}},
        {"unknown_field": 1},
    ],
)
def test_invalid_profiles_are_rejected(persona: Persona, changes: dict[str, Any]) -> None:
    assert put(persona, **changes).status_code == 422


def test_blank_text_is_stored_as_unset(persona: Persona) -> None:
    body = put(persona, headline="   ", summary="", current_location="  ").json()

    assert body["headline"] is None
    assert body["summary"] is None
    assert body["current_location"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"current_location": "Another Place"},
        {"relocation_preference": "not_open"},
        {"remote_preference": "remote_only"},
        {"work_authorization": [{"country": "CA", "status": "Sample", "sponsorship_needed": None}]},
        {"work_authorization": []},
    ],
)
def test_constraint_edits_bump_constraints_updated_at(
    persona: Persona, owner_session: Session, changes: dict[str, Any]
) -> None:
    put(persona)
    before = constraints_stamp(owner_session)

    assert put(persona, **changes).status_code == 200

    assert constraints_stamp(owner_session) > before


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"headline": "A different headline"},
        {"summary": "A different summary"},
        {"target_roles": [{"name": "Other Role", "priority": "low", "notes": ""}]},
        {"communication_preferences": {"tone": "warm", "length": "", "sign_off": "", "avoid": []}},
    ],
)
def test_other_edits_do_not_bump_constraints_updated_at(
    persona: Persona, owner_session: Session, changes: dict[str, Any]
) -> None:
    put(persona)
    before = constraints_stamp(owner_session)

    assert put(persona, **changes).status_code == 200

    assert constraints_stamp(owner_session) == before


def test_updated_at_moves_when_anything_changes(persona: Persona) -> None:
    first = put(persona).json()

    second = put(persona, headline="Changed").json()

    assert second["updated_at"] > first["updated_at"]
    assert second["constraints_updated_at"] == first["constraints_updated_at"]
