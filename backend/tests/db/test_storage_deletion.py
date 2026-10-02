import io
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.deletion import make_storage_deletion_hook
from app.artifacts.storage import FilesystemStorage, user_prefix
from app.auth.deletion import DeletionHooks
from app.config import Settings
from app.jobs.handlers import register_job_handlers
from app.jobs.registry import JobRegistry
from app.jobs.runner import JobRunner
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import make_persona
from tests.db.resume_helpers import create_lane, stored_files, upload
from tests.synthetic import synthetic_pdf

pytestmark = pytest.mark.db

CONFIRMATION = {"confirm": "DELETE MY ACCOUNT"}
TABLES = ("profiles", "artifacts", "resumes", "resume_lanes")


def counts(owner: Session, user_id: object) -> dict[str, int]:
    owner.rollback()
    return {
        table: owner.execute(
            text(f"SELECT count(*) FROM {table} WHERE user_id = :id"),  # noqa: S608
            {"id": user_id},
        ).scalar_one()
        for table in TABLES
    }


def test_account_deletion_removes_the_users_files_rows_and_nothing_else(
    app: FastAPI,
    idp: FakeIdentityProvider,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    target = make_persona(app, idp, "a")
    bystander = make_persona(app, idp, "b")
    for persona in (target, bystander):
        lane = create_lane(persona)
        upload(persona, synthetic_pdf(f"keep-{persona.label}"), lane_id=lane["id"])
        upload(persona, synthetic_pdf(f"keep2-{persona.label}"))
        persona.request("PUT", "/api/v1/profile", json={"headline": "synthetic"})
    storage = FilesystemStorage(db_settings.artifact_storage_dir)
    assert len(stored_files(db_settings.artifact_storage_dir)) == 4
    bystander_rows = counts(owner_session, bystander.user_id)
    target.request("POST", "/api/v1/account/deletion", json=CONFIRMATION)
    registry = JobRegistry()
    register_job_handlers(registry, DeletionHooks(), storage=storage, settings=db_settings)
    runner = JobRunner(app_sessions, registry, db_settings, worker_id="deletion")

    while runner.run_once():
        pass

    assert counts(owner_session, target.user_id) == dict.fromkeys(TABLES, 0)
    assert counts(owner_session, bystander.user_id) == bystander_rows
    remaining = stored_files(db_settings.artifact_storage_dir)
    assert len(remaining) == 2
    assert all(f"users/{bystander.user_id}/" in path.as_posix() for path in remaining)
    assert not (db_settings.artifact_storage_dir / "users" / str(target.user_id)).exists()
    assert bystander.client.get("/api/v1/resumes").status_code == 200
    assert len(bystander.client.get("/api/v1/resumes").json()) == 2


def test_the_storage_hook_is_idempotent(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    storage = FilesystemStorage(db_settings.artifact_storage_dir)
    hook = make_storage_deletion_hook(storage)
    user_id = uuid.uuid4()
    storage.put(f"{user_prefix(user_id)}artifacts/a", io.BytesIO(b"x"))

    with app_sessions() as session:
        hook(session, user_id)
        hook(session, user_id)

    assert stored_files(db_settings.artifact_storage_dir) == []
