import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.jobs.queue import enqueue
from app.opportunities import extraction as extraction_module
from app.opportunities.jobs import ExtractJdPayload
from tests.db.auth_helpers import Persona
from tests.db.opportunity_helpers import (
    SYNTHETIC_JD,
    extraction_json,
    extractor_gateway,
    get_opportunity,
    ingest_and_extract,
    ingest_ok,
    run_extraction_jobs,
    scalar,
)
from tests.db.test_extraction_job import extraction_state, job_state, other, persona  # noqa: F401

pytestmark = pytest.mark.db

OPPORTUNITIES = "/api/v1/opportunities"


def insert_settled_run(
    owner: Session, user_id: Any, artifact_id: str, output: dict[str, Any] | None
) -> str:
    identifier = str(uuid.uuid4())
    manifest = {
        "schema_version": 1,
        "entries": [{"entity_type": "artifact", "entity_id": artifact_id, "version": 0}],
    }
    owner.rollback()
    owner.execute(
        text(
            "INSERT INTO llm_runs (id, user_id, purpose, prompt_id, prompt_version, provider, "
            "model, tier, max_output_tokens, attempt, status, input_tokens, output_tokens, "
            "latency_ms, reserved_cost_usd, cost_usd, context_manifest, output, created_at, "
            "settled_at) VALUES (:id, :user_id, 'extract_jd', 'jd.extract', 1, 'fake', "
            "'fake-fast', 'fast', 100, 1, 'succeeded', 1, 1, 1, 0.001, 0.0001, "
            "CAST(:manifest AS jsonb), CAST(:output AS jsonb), now(), now())"
        ),
        {
            "id": identifier,
            "user_id": user_id,
            "manifest": json.dumps(manifest),
            "output": None if output is None else json.dumps(output),
        },
    )
    owner.commit()
    return identifier


def make_retry_due(owner: Session) -> None:
    owner.rollback()
    owner.execute(text("UPDATE jobs SET run_after = now() - interval '1 second'"))
    owner.commit()


def test_a_queue_retry_after_the_model_answered_reuses_the_settled_run(
    persona: Persona,  # noqa: F811
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    gateway, provider = extractor_gateway(app_sessions, [extraction_json()])
    real_apply = extraction_module.apply_extraction
    attempts: list[int] = []

    def flaky_apply(*args: Any, **kwargs: Any) -> bool:
        attempts.append(1)
        if len(attempts) == 1:
            raise OperationalError("simulated", None, Exception("database went away"))
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(extraction_module, "apply_extraction", flaky_apply)

    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert extraction_state(owner_session, opportunity_id).extraction_status == "pending"
    assert job_state(owner_session, opportunity_id).status == "queued"
    make_retry_due(owner_session)
    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert len(provider.requests) == 1
    assert scalar(owner_session, "SELECT count(*) FROM llm_runs") == 1
    run_id = scalar(owner_session, "SELECT id FROM llm_runs")
    state = extraction_state(owner_session, opportunity_id)
    assert state.extraction_status == "succeeded"
    assert state.llm_run_id == run_id
    assert state.title == "Senior Widget Engineer"
    job = job_state(owner_session, opportunity_id)
    assert (job.status, job.attempts) == ("succeeded", 2)
    assert (
        scalar(
            owner_session, "SELECT count(*) FROM qualifications WHERE llm_run_id = :id", id=run_id
        )
        == 5
    )


def test_a_stored_output_that_fails_validation_is_not_replaced_by_a_new_call(
    persona: Persona,  # noqa: F811
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    artifact_id = get_opportunity(persona, opportunity_id)["jd_artifact_id"]
    bad_run = insert_settled_run(
        owner_session, persona.user_id, artifact_id, {"schema_version": 1, "data": {"bogus": 1}}
    )
    gateway, provider = extractor_gateway(app_sessions, [extraction_json()])

    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert provider.requests == []
    state = extraction_state(owner_session, opportunity_id)
    assert (state.extraction_status, state.extraction_error_code) == (
        "failed",
        "stored_output_invalid",
    )
    assert str(state.llm_run_id) == bad_run
    assert job_state(owner_session, opportunity_id).status == "succeeded"
    assert run_extraction_jobs(app_sessions, db_settings, gateway) == 0

    retried = persona.request("POST", f"{OPPORTUNITIES}/{opportunity_id}/extract")
    assert retried.status_code == 202
    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert len(provider.requests) == 1
    assert get_opportunity(persona, opportunity_id)["extraction_status"] == "succeeded"
    assert scalar(owner_session, "SELECT count(*) FROM llm_runs") == 2


def test_a_run_without_stored_output_is_also_stored_output_invalid(
    persona: Persona,  # noqa: F811
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    artifact_id = get_opportunity(persona, opportunity_id)["jd_artifact_id"]
    insert_settled_run(owner_session, persona.user_id, artifact_id, None)
    gateway, provider = extractor_gateway(app_sessions, [extraction_json()])

    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert provider.requests == []
    assert (
        extraction_state(owner_session, opportunity_id).extraction_error_code
        == "stored_output_invalid"
    )


def test_another_users_settled_run_is_never_reused(
    persona: Persona,  # noqa: F811
    other: Persona,  # noqa: F811
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    opportunity_id = ingest_ok(persona, SYNTHETIC_JD)
    artifact_id = get_opportunity(persona, opportunity_id)["jd_artifact_id"]
    planted = {"schema_version": 1, "data": json.loads(extraction_json(title="Planted"))}
    foreign_run = insert_settled_run(owner_session, other.user_id, artifact_id, planted)
    gateway, provider = extractor_gateway(app_sessions, [extraction_json()])

    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert len(provider.requests) == 1
    detail = get_opportunity(persona, opportunity_id)
    assert detail["title"] == "Senior Widget Engineer"
    assert detail["llm_run_id"] != foreign_run
    assert (
        scalar(
            owner_session,
            "SELECT count(*) FROM llm_runs WHERE user_id = :id",
            id=persona.user_id,
        )
        == 1
    )


def test_a_run_already_applied_to_the_opportunity_is_not_reused(
    persona: Persona,  # noqa: F811
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    opportunity_id = ingest_and_extract(persona, app_sessions, db_settings, [extraction_json()])
    owner_session.rollback()
    owner_session.execute(
        text("UPDATE opportunities SET extraction_status = 'pending' WHERE id = :id"),
        {"id": opportunity_id},
    )
    owner_session.commit()
    with app_sessions() as session:
        enqueue(
            session,
            kind="extract_jd",
            payload=ExtractJdPayload(opportunity_id=uuid.UUID(opportunity_id)),
            user_id=persona.user_id,
        )
        session.commit()
    gateway, provider = extractor_gateway(app_sessions, [extraction_json(title="Second answer")])

    run_extraction_jobs(app_sessions, db_settings, gateway)

    assert len(provider.requests) == 1
    assert get_opportunity(persona, opportunity_id)["title"] == "Senior Widget Engineer"
