from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import ApplicationStage
from app.state_machines.application import (
    ApplicationEventType,
    EventRecord,
    Projection,
    application_projection,
)
from tests.db.auth_helpers import Persona
from tests.db.opportunity_helpers import get_opportunity, ingest_ok, jd_variant

OPPORTUNITIES = "/api/v1/opportunities"
APPLICATIONS = "/api/v1/applications"


def when(minutes: float = 0, *, days: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes, days=days)).isoformat()


def new_opportunity(persona: Persona, label: str) -> dict[str, Any]:
    return get_opportunity(persona, ingest_ok(persona, jd_variant(label)))


def decide(
    persona: Persona, opportunity: dict[str, Any], action: str, **extra: Any
) -> httpx2.Response:
    body = {"expected_state_version": opportunity["state_version"], **extra}
    return persona.request("POST", f"{OPPORTUNITIES}/{opportunity['id']}/{action}", json=body)


def apply_to(persona: Persona, opportunity: dict[str, Any], **extra: Any) -> httpx2.Response:
    return decide(persona, opportunity, "apply", **extra)


def applied(persona: Persona, label: str, **extra: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    opportunity = new_opportunity(persona, label)
    response = apply_to(persona, opportunity, **extra)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["opportunity"], body["application"]


def record(
    persona: Persona,
    application: dict[str, Any],
    event_type: str,
    occurred_at: str | None = None,
    **extra: Any,
) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{APPLICATIONS}/{application['id']}/events",
        json={
            "expected_state_version": application["state_version"],
            "event_type": event_type,
            "occurred_at": occurred_at or when(),
            **extra,
        },
    )


def void(
    persona: Persona, application: dict[str, Any], event_id: str, **extra: Any
) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{APPLICATIONS}/{application['id']}/events/{event_id}/void",
        json={"expected_state_version": application["state_version"], **extra},
    )


def reopen(persona: Persona, application: dict[str, Any], **extra: Any) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{APPLICATIONS}/{application['id']}/reopen",
        json={"expected_state_version": application["state_version"], **extra},
    )


def current(persona: Persona, application: dict[str, Any]) -> dict[str, Any]:
    response = persona.request("GET", f"{APPLICATIONS}/{application['id']}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def timeline(persona: Persona, opportunity_id: str) -> list[dict[str, Any]]:
    response = persona.request("GET", f"{OPPORTUNITIES}/{opportunity_id}/timeline")
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def entry_for(entries: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    return next(entry for entry in entries if entry["event_type"] == event_type)


def error_code(response: httpx2.Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


def stored_records(owner: Session, application_id: str) -> list[EventRecord]:
    owner.rollback()
    rows = owner.execute(
        text(
            "SELECT id, event_type, occurred_at, recorded_at, voids_event_id FROM domain_events "
            "WHERE aggregate_type = 'application' AND aggregate_id = :id"
        ),
        {"id": application_id},
    ).all()
    return [
        EventRecord(
            id=row.id,
            event_type=ApplicationEventType(row.event_type),
            occurred_at=row.occurred_at,
            recorded_at=row.recorded_at,
            voids_event_id=row.voids_event_id,
        )
        for row in rows
    ]


def stored_state(owner: Session, application_id: str) -> tuple[Projection, Projection]:
    owner.rollback()
    row = owner.execute(
        text("SELECT stage, is_terminal FROM applications WHERE id = :id"), {"id": application_id}
    ).one()
    stored = Projection(ApplicationStage(row.stage), row.is_terminal)
    return stored, application_projection(stored_records(owner, application_id))
