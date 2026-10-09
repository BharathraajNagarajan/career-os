import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.db.auth_helpers import Persona

CONTACTS = "/api/v1/contacts"
INTERACTIONS = "/api/v1/interactions"
ACTIONS = "/api/v1/actions"
RULES = "/api/v1/strategy-rules"
COMPANIES = "/api/v1/companies"
EMPTY_EMAILS = {"schema_version": 1, "items": []}


def insert_row(session: Session, table: str, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid.uuid4())
    columns = ", ".join(values)
    placeholders = ", ".join(
        f"CAST(:{name} AS jsonb)" if isinstance(value, dict) else f":{name}"
        for name, value in values.items()
    )
    params = {
        name: json.dumps(value) if isinstance(value, dict) else value
        for name, value in values.items()
    }
    session.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), params)  # noqa: S608
    row_id: uuid.UUID = values["id"]
    return row_id


def future(minutes: float = 0, *, days: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes, days=days)).isoformat()


def error_code(response: httpx2.Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


def body_of(response: httpx2.Response, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def create_contact(
    persona: Persona, name: str = "Alex Example", emails: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    payload = {"full_name": name, "emails": emails or [], **extra}
    return body_of(persona.request("POST", CONTACTS, json=payload), 201)


def get_contact(persona: Persona, contact_id: str) -> dict[str, Any]:
    return body_of(persona.request("GET", f"{CONTACTS}/{contact_id}"))


def create_company(persona: Persona, name: str = "Example Corp") -> dict[str, Any]:
    return body_of(persona.request("POST", COMPANIES, json={"name": name}), 201)


def patch_contact(persona: Persona, contact: dict[str, Any], **changes: Any) -> httpx2.Response:
    return persona.request(
        "PATCH",
        f"{CONTACTS}/{contact['id']}",
        json={"expected_updated_at": contact["updated_at"], **changes},
    )


def merge(persona: Persona, survivor: dict[str, Any], merged: dict[str, Any]) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{CONTACTS}/{survivor['id']}/merge",
        json={
            "merged_id": merged["id"],
            "expected_survivor_updated_at": survivor["updated_at"],
            "expected_merged_updated_at": merged["updated_at"],
        },
    )


def create_interaction(persona: Persona, contact_id: str, **extra: Any) -> httpx2.Response:
    payload = {
        "contact_id": contact_id,
        "channel": "email",
        "direction": "outbound",
        "occurred_at": future(-5),
        **extra,
    }
    return persona.request("POST", INTERACTIONS, json=payload)


def create_action(persona: Persona, kind: str = "custom", **extra: Any) -> httpx2.Response:
    return persona.request(
        "POST", ACTIONS, json={"kind": kind, "title": "Follow up with Alex Example", **extra}
    )


def action_command(
    persona: Persona, action: dict[str, Any], command: str, **extra: Any
) -> httpx2.Response:
    return persona.request(
        "POST",
        f"{ACTIONS}/{action['id']}/{command}",
        json={"expected_state_version": action["state_version"], **extra},
    )
