import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.deletion import DeleteAccountPayload, DeletionHooks, make_delete_account_handler
from app.config import Settings
from app.jobs.handlers import register_job_handlers
from app.jobs.registry import JobContext, JobRegistry
from app.jobs.runner import JobRunner
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.factories import make_event

pytestmark = pytest.mark.db

CONFIRMATION = {"confirm": "DELETE MY ACCOUNT"}

OWNED_TABLES = ("users", "auth_identities", "sessions", "domain_events")
COUNT_QUERIES = {
    "users": "SELECT count(*) FROM users WHERE id = :id",
    "auth_identities": "SELECT count(*) FROM auth_identities WHERE user_id = :id",
    "sessions": "SELECT count(*) FROM sessions WHERE user_id = :id",
    "domain_events": "SELECT count(*) FROM domain_events WHERE user_id = :id",
}


def rows_for(owner: Session, user_id: uuid.UUID) -> dict[str, int]:
    owner.rollback()
    return {
        table: owner.execute(text(query), {"id": user_id}).scalar_one()
        for table, query in COUNT_QUERIES.items()
    }


def worker(
    app_sessions: sessionmaker[Session], settings: Settings, hooks: DeletionHooks
) -> JobRunner:
    registry = JobRegistry()
    register_job_handlers(registry, hooks)
    return JobRunner(app_sessions, registry, settings, worker_id="deletion-test")


def seed_events(app_sessions: sessionmaker[Session], persona: Persona) -> None:
    with app_sessions() as session:
        make_event(session, persona.user_id)
        session.commit()


def test_deletion_requires_the_typed_confirmation(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    wrong = persona.request("POST", "/api/v1/account/deletion", json={"confirm": "yes"})
    missing = persona.request("POST", "/api/v1/account/deletion", json={})

    assert wrong.status_code == 422
    assert missing.status_code == 422
    assert persona.client.get("/api/v1/auth/me").status_code == 200


def test_deletion_needs_csrf(app: FastAPI, idp: FakeIdentityProvider) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.client.post("/api/v1/account/deletion", json=CONFIRMATION)

    assert response.status_code == 403


def test_request_marks_user_drops_sessions_and_enqueues_a_system_job(
    app: FastAPI, idp: FakeIdentityProvider, owner_session: Session
) -> None:
    persona = make_persona(app, idp, "a")

    response = persona.request("POST", "/api/v1/account/deletion", json=CONFIRMATION)

    assert response.status_code == 202
    assert any("Max-Age=0" in item for item in response.headers.get_list("set-cookie"))
    status: str = owner_session.execute(text("SELECT status FROM users")).scalar_one()
    job = owner_session.execute(text("SELECT kind, user_id, unique_key, payload FROM jobs")).one()
    assert status == "deletion_requested"
    assert rows_for(owner_session, persona.user_id)["sessions"] == 0
    assert job.kind == "delete_account"
    assert job.user_id is None
    assert job.unique_key == f"delete_account:{persona.user_id}"
    assert job.payload == {"user_id": str(persona.user_id)}
    assert persona.client.get("/api/v1/auth/me").status_code == 401


def test_worker_removes_every_row_of_the_user_and_leaves_others(
    app: FastAPI,
    idp: FakeIdentityProvider,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    target = make_persona(app, idp, "a")
    bystander = make_persona(app, idp, "b")
    seed_events(app_sessions, target)
    seed_events(app_sessions, bystander)
    bystander_before = rows_for(owner_session, bystander.user_id)
    target.request("POST", "/api/v1/account/deletion", json=CONFIRMATION)

    ran = worker(app_sessions, db_settings, DeletionHooks()).run_once()

    assert ran is True
    assert rows_for(owner_session, target.user_id) == dict.fromkeys(OWNED_TABLES, 0)
    assert rows_for(owner_session, bystander.user_id) == bystander_before
    assert bystander.client.get("/api/v1/auth/me").status_code == 200
    job_status: str = owner_session.execute(text("SELECT status FROM jobs")).scalar_one()
    assert job_status == "succeeded"


def test_registered_hooks_run_before_the_user_row_is_removed(
    app: FastAPI,
    idp: FakeIdentityProvider,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    persona = make_persona(app, idp, "a")
    persona.request("POST", "/api/v1/account/deletion", json=CONFIRMATION)
    seen: list[tuple[uuid.UUID, int]] = []
    hooks = DeletionHooks()

    def hook(session: Session, user_id: uuid.UUID) -> None:
        present = session.execute(
            text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
        )
        seen.append((user_id, present.scalar_one()))

    hooks.register("test_objects", hook)
    worker(app_sessions, db_settings, hooks).run_once()

    assert seen == [(persona.user_id, 1)]
    assert rows_for(owner_session, persona.user_id)["users"] == 0


def test_handler_refuses_a_user_that_did_not_request_deletion(
    app: FastAPI,
    idp: FakeIdentityProvider,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
) -> None:
    persona = make_persona(app, idp, "a")
    handler = make_delete_account_handler(DeletionHooks())
    with app_sessions() as session, pytest.raises(PermissionError):
        handler(
            JobContext(session, uuid.uuid4(), None, None),
            DeleteAccountPayload(user_id=persona.user_id),
        )

    assert rows_for(owner_session, persona.user_id)["users"] == 1


def test_handler_is_idempotent_when_the_user_is_already_gone(
    app_sessions: sessionmaker[Session],
) -> None:
    handler = make_delete_account_handler(DeletionHooks())

    with app_sessions() as session:
        handler(
            JobContext(session, uuid.uuid4(), None, None),
            DeleteAccountPayload(user_id=uuid.uuid4()),
        )
