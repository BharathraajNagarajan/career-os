import json
import uuid
from collections.abc import Iterable
from typing import Any

import httpx2
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.jobs.registry import JobRegistry
from app.jobs.runner import JobRunner
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider, Scripted
from app.opportunities.extraction import make_extract_jd_handler
from app.opportunities.jobs import EXTRACT_JD_JOB, ExtractJdPayload
from tests.db.auth_helpers import Persona
from tests.db.llm_helpers import make_gateway

SYNTHETIC_JD = (
    "Example Corp is hiring a Senior Widget Engineer for the Platform team.\n"
    "Job ID: EX-1001\n"
    "Location: Springfield, IL, USA (hybrid)\n\n"
    "Minimum qualifications\n"
    "- 5+ years of experience building widgets\n"
    "- Proficiency in Python and SQL\n"
    "- Authorized to work in the United States\n\n"
    "Preferred qualifications\n"
    "- Experience with Kubernetes\n"
    "- Bachelor's degree in a related field\n\n"
    "Example Corp is an equal opportunity employer.\n"
)

Q_YEARS = "5+ years of experience building widgets"
Q_PYTHON = "Proficiency in Python and SQL"
Q_AUTH = "Authorized to work in the United States"
Q_KUBE = "Experience with Kubernetes"
Q_DEGREE = "Bachelor's degree in a related field"


def jd_variant(label: str) -> str:
    return f"{SYNTHETIC_JD}Reference: {label}\n"


def qualification(
    text_verbatim: str,
    *,
    kind: str = "minimum",
    category: str = "skill",
    skill_keys: Iterable[str] = (),
    min_years: float | None = None,
    is_hard_constraint: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "text_verbatim": text_verbatim,
        "category": category,
        "skill_keys": list(skill_keys),
        "min_years": min_years,
        "is_hard_constraint": is_hard_constraint,
    }


def default_qualifications() -> list[dict[str, Any]]:
    return [
        qualification(Q_YEARS, category="experience", skill_keys=["widgets"], min_years=5),
        qualification(Q_PYTHON, skill_keys=["Python", "SQL"]),
        qualification(Q_AUTH, category="authorization", is_hard_constraint=True, skill_keys=[]),
        qualification(Q_KUBE, kind="preferred", skill_keys=["kubernetes"]),
        qualification(Q_DEGREE, kind="preferred", category="education"),
    ]


def extraction_json(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "company_name": "Example Corp",
        "company_domain": "example.test",
        "title": "Senior Widget Engineer",
        "team": "Platform",
        "external_job_id": "EX-1001",
        "location_text": "Springfield, IL, USA (hybrid)",
        "locations": [{"city": "Springfield", "region": "IL", "country": "US"}],
        "workplace_type": "hybrid",
        "qualifications": default_qualifications(),
    }
    base.update(overrides)
    return json.dumps(base)


def ingest(persona: Persona, jd_text: str, **extra: Any) -> httpx2.Response:
    return persona.request(
        "POST", "/api/v1/opportunities/ingest", json={"jd_text": jd_text, **extra}
    )


def ingest_ok(persona: Persona, jd_text: str, **extra: Any) -> str:
    response = ingest(persona, jd_text, **extra)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def extractor_gateway(
    app_sessions: sessionmaker[Session], script: Iterable[Scripted], *, cap: str = "1.00"
) -> tuple[ModelGateway, FakeProvider]:
    return make_gateway(app_sessions, script=script, cap=cap)


def run_extraction_jobs(
    app_sessions: sessionmaker[Session], settings: Settings, gateway: ModelGateway
) -> int:
    registry = JobRegistry()
    registry.register(EXTRACT_JD_JOB, ExtractJdPayload, make_extract_jd_handler(gateway, settings))
    runner = JobRunner(app_sessions, registry, settings, worker_id="extract-test")
    processed = 0
    while runner.run_once():
        processed += 1
    return processed


def ingest_and_extract(
    persona: Persona,
    app_sessions: sessionmaker[Session],
    settings: Settings,
    script: Iterable[Scripted],
    jd_text: str = SYNTHETIC_JD,
    **extra: Any,
) -> str:
    opportunity_id = ingest_ok(persona, jd_text, **extra)
    gateway, _ = extractor_gateway(app_sessions, script)
    run_extraction_jobs(app_sessions, settings, gateway)
    return opportunity_id


def get_opportunity(persona: Persona, opportunity_id: str) -> dict[str, Any]:
    response = persona.request("GET", f"/api/v1/opportunities/{opportunity_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def row(owner: Session, sql: str, **params: Any) -> Any:
    owner.rollback()
    return owner.execute(text(sql), params).one()


def rows(owner: Session, sql: str, **params: Any) -> list[Any]:
    owner.rollback()
    return list(owner.execute(text(sql), params).all())


def scalar(owner: Session, sql: str, **params: Any) -> Any:
    owner.rollback()
    return owner.execute(text(sql), params).scalar_one()


def new_uuid() -> str:
    return str(uuid.uuid4())
