import uuid
from pathlib import Path
from typing import Any

import httpx2
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.db.auth_helpers import Persona


def upload(
    persona: Persona,
    content: bytes,
    filename: str = "Sample Resume.pdf",
    *,
    label: str | None = None,
    lane_id: str | uuid.UUID | None = None,
    content_type: str = "application/octet-stream",
) -> httpx2.Response:
    fields: dict[str, str] = {}
    if label is not None:
        fields["label"] = label
    if lane_id is not None:
        fields["lane_id"] = str(lane_id)
    return persona.request(
        "POST",
        "/api/v1/resumes",
        files={"file": (filename, content, content_type)},
        data=fields,
    )


def create_lane(persona: Persona, name: str = "Platform", **extra: Any) -> dict[str, Any]:
    response = persona.request("POST", "/api/v1/lanes", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def lane_updated_at(owner: Session, lane_id: str) -> Any:
    owner.rollback()
    return owner.execute(
        text("SELECT updated_at FROM resume_lanes WHERE id = :id"), {"id": lane_id}
    ).scalar_one()


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
