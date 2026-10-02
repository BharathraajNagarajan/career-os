import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import ProposalType
from app.llm.errors import LlmBudgetExhausted
from app.review.handlers import ReviewHandlerRegistry
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona, new_client
from tests.db.llm_helpers import VALID, make_gateway, structured
from tests.db.review_helpers import RecordingRegistry, create_item

pytestmark = pytest.mark.db

ITEMS = "/api/v1/review-items"


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


@pytest.fixture
def other(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "b")


def registry_of(app: FastAPI) -> RecordingRegistry:
    registry = app.state.review_registry
    assert isinstance(registry, RecordingRegistry)
    return registry


def add_item(app: FastAPI, app_sessions: sessionmaker[Session], who: Persona, **kwargs: Any) -> str:
    registry: ReviewHandlerRegistry = app.state.review_registry
    return str(create_item(app_sessions, registry, who.user_id, **kwargs))


def test_budget_starts_at_zero_and_reports_money_as_strings(persona: Persona) -> None:
    response = persona.request("GET", "/api/v1/llm/budget")

    body = response.json()
    assert response.status_code == 200
    assert Decimal(body["spent_usd"]) == 0
    assert Decimal(body["cap_usd"]) == Decimal("1.00")
    assert Decimal(body["remaining_usd"]) == Decimal("1.00")
    assert all(isinstance(body[key], str) for key in ("spent_usd", "cap_usd", "remaining_usd"))


def test_budget_reflects_spend_and_resets_at_the_next_utc_midnight(
    app_sessions: sessionmaker[Session], persona: Persona, other: Persona
) -> None:
    gateway, _ = make_gateway(app_sessions, script=[VALID])
    structured(gateway, persona.user_id)

    mine = persona.request("GET", "/api/v1/llm/budget").json()
    theirs = other.request("GET", "/api/v1/llm/budget").json()

    assert Decimal(mine["spent_usd"]) > 0
    assert Decimal(mine["remaining_usd"]) == Decimal(mine["cap_usd"]) - Decimal(mine["spent_usd"])
    assert Decimal(theirs["spent_usd"]) == 0
    resets_at = datetime.fromisoformat(mine["resets_at"])
    assert resets_at > datetime.now(UTC)
    assert (resets_at.hour, resets_at.minute, resets_at.second) == (0, 0, 0)


def test_remaining_budget_never_goes_negative(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona, db_settings: Settings
) -> None:
    gateway, _ = make_gateway(app_sessions, script=[VALID])
    structured(gateway, persona.user_id)
    app.state.settings = db_settings.model_copy(update={"llm_daily_cost_cap_usd": Decimal("0.00")})

    body = persona.request("GET", "/api/v1/llm/budget").json()

    assert Decimal(body["remaining_usd"]) == 0
    assert Decimal(body["spent_usd"]) > 0


def test_a_refused_model_call_surfaces_as_429_with_a_typed_code(
    app: FastAPI, persona: Persona
) -> None:
    @app.get("/api/v1/test-only/refused")
    def refused() -> None:
        raise LlmBudgetExhausted("x")

    response = persona.request("GET", "/api/v1/test-only/refused")

    assert response.status_code == 429
    assert response.json() == {"error": {"code": "llm_budget_exhausted"}}


def test_review_list_returns_only_pending_items_newest_first(
    app: FastAPI,
    app_sessions: sessionmaker[Session],
    persona: Persona,
    other: Persona,
) -> None:
    first = add_item(app, app_sessions, persona, name="first")
    second = add_item(app, app_sessions, persona, name="second")
    add_item(app, app_sessions, other, name="foreign")
    rejected = persona.request(
        "POST", f"{ITEMS}/{first}/reject", json={"expected_state_version": 1}
    )
    assert rejected.status_code == 200

    pending = persona.request("GET", ITEMS, params={"status": "pending"}).json()
    everything = persona.request("GET", ITEMS).json()

    assert [row["id"] for row in pending] == [second]
    assert [row["id"] for row in everything] == [second, first]
    assert pending[0]["proposed_payload"] == {"schema_version": 1, "name": "second"}
    assert pending[0]["confirmable"] is True
    assert persona.request("GET", ITEMS, params={"status": "nonsense"}).status_code == 422


def test_confirm_applies_the_domain_command_through_the_api(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona, name="Applied name")

    response = persona.request(
        "POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 1}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["state_version"]) == ("confirmed", 2)
    assert persona.request("GET", "/api/v1/profile").json()["headline"] == "Applied name"
    assert registry_of(app).recorder.calls == [(uuid.UUID(item), "Applied name")]


def test_edit_confirm_applies_the_edited_payload(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona, name="Original")

    response = persona.request(
        "POST",
        f"{ITEMS}/{item}/edit-confirm",
        json={"expected_state_version": 1, "payload": {"schema_version": 1, "name": "Edited"}},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["decided_payload"] == {"schema_version": 1, "name": "Edited"}
    assert body["proposed_payload"]["name"] == "Original"
    assert persona.request("GET", "/api/v1/profile").json()["headline"] == "Edited"


def test_edit_confirm_rejects_an_invalid_payload(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona)

    response = persona.request(
        "POST",
        f"{ITEMS}/{item}/edit-confirm",
        json={"expected_state_version": 1, "payload": {"schema_version": 1, "name": ""}},
    )

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_payload"}}
    assert persona.request("GET", f"{ITEMS}/{item}").json()["status"] == "pending"


def test_reject_stores_the_note(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona)

    response = persona.request(
        "POST",
        f"{ITEMS}/{item}/reject",
        json={"expected_state_version": 1, "note": "not recruiting"},
    )

    body = response.json()
    assert (body["status"], body["decision_note"]) == ("rejected", "not recruiting")
    assert registry_of(app).recorder.calls == []


def test_a_stale_version_is_a_409_conflict(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona)

    response = persona.request(
        "POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 5}
    )

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "conflict"}}


def test_deciding_twice_is_a_409_invalid_transition(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona)
    persona.request("POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 1})

    again = persona.request("POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 2})
    edit = persona.request(
        "POST",
        f"{ITEMS}/{item}/edit-confirm",
        json={"expected_state_version": 2, "payload": {"schema_version": 1, "name": "x"}},
    )
    reject = persona.request("POST", f"{ITEMS}/{item}/reject", json={"expected_state_version": 2})

    for response in (again, edit, reject):
        assert response.status_code == 409
        assert response.json() == {"error": {"code": "invalid_transition"}}
    assert len(registry_of(app).recorder.calls) == 1


def test_an_item_without_a_handler_is_422_to_confirm_but_can_be_rejected(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(
        app,
        app_sessions,
        persona,
        proposal_type=ProposalType.CLAIM,
        payload={"schema_version": 1, "text": "x"},
    )
    assert persona.request("GET", f"{ITEMS}/{item}").json()["confirmable"] is False

    confirm = persona.request("POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 1})
    reject = persona.request("POST", f"{ITEMS}/{item}/reject", json={"expected_state_version": 1})

    assert confirm.status_code == 422
    assert confirm.json() == {"error": {"code": "no_handler"}}
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


def test_decisions_need_the_csrf_token_and_a_valid_body(
    app: FastAPI, app_sessions: sessionmaker[Session], persona: Persona
) -> None:
    item = add_item(app, app_sessions, persona)

    no_token = persona.client.post(
        f"{ITEMS}/{item}/confirm", json={"expected_state_version": 1}, headers={"X-CSRF-Token": ""}
    )
    bad_body = persona.request(
        "POST", f"{ITEMS}/{item}/confirm", json={"expected_state_version": 0}
    )
    extra = persona.request(
        "POST", f"{ITEMS}/{item}/reject", json={"expected_state_version": 1, "surprise": 1}
    )

    assert no_token.status_code == 403
    assert bad_body.status_code == 422
    assert extra.status_code == 422
    assert new_client(app).get(ITEMS).status_code == 401
