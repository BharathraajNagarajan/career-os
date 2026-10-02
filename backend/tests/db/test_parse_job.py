import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.extraction import (
    ExtractionError,
    ExtractionLimits,
    ExtractionResult,
)
from app.artifacts.outline import build_outline
from app.artifacts.sniff import FileKind
from app.artifacts.storage import FilesystemStorage
from app.auth.deletion import DeletionHooks
from app.config import Settings
from app.jobs.handlers import register_job_handlers
from app.jobs.registry import JobContext, JobRegistry
from app.jobs.runner import JobRunner
from app.resumes.parse_job import (
    PARSE_RESUME_JOB,
    ParseResumePayload,
    make_parse_resume_handler,
)
from tests.auth.fake_idp import FakeIdentityProvider
from tests.db.auth_helpers import Persona, make_persona
from tests.db.resume_helpers import upload
from tests.synthetic import synthetic_docx, synthetic_pdf

pytestmark = pytest.mark.db


class RecordingExtractor:
    def __init__(self, result: ExtractionResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[int, FileKind]] = []

    def __call__(self, data: bytes, kind: FileKind, limits: ExtractionLimits) -> ExtractionResult:
        self.calls.append((len(data), kind))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def success_result() -> ExtractionResult:
    text_value = "Sample Person\nSUMMARY\nSynthetic text\nSkills:\nWidgets\n"
    return ExtractionResult(None, text_value, build_outline(text_value))


@pytest.fixture
def persona(app: FastAPI, idp: FakeIdentityProvider) -> Persona:
    return make_persona(app, idp, "a")


def runner_with(
    app_sessions: sessionmaker[Session], settings: Settings, extractor: RecordingExtractor
) -> JobRunner:
    registry = JobRegistry()
    handler = make_parse_resume_handler(
        FilesystemStorage(settings.artifact_storage_dir), settings, extractor
    )
    registry.register(PARSE_RESUME_JOB, ParseResumePayload, handler)
    return JobRunner(app_sessions, registry, settings, worker_id="parse-test")


def state(owner: Session, resume_id: str) -> Any:
    owner.rollback()
    return owner.execute(
        text(
            "SELECT a.extraction_status, a.extraction_error_code, a.extracted_text, "
            "r.parsed_outline FROM resumes r JOIN artifacts a ON a.id = r.artifact_id "
            "WHERE r.id = :id"
        ),
        {"id": resume_id},
    ).one()


def job_row(owner: Session) -> Any:
    owner.rollback()
    return owner.execute(text("SELECT status, attempts, last_error_code FROM jobs")).one()


def test_success_stores_text_and_outline(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    resume = upload(persona, synthetic_pdf("parse")).json()
    extractor = RecordingExtractor(success_result())

    assert runner_with(app_sessions, db_settings, extractor).run_once() is True

    row = state(owner_session, resume["id"])
    assert row.extraction_status == "succeeded"
    assert row.extraction_error_code is None
    assert row.extracted_text.startswith("Sample Person")
    assert row.parsed_outline["schema_version"] == 1
    assert [s["heading"] for s in row.parsed_outline["sections"]] == ["SUMMARY", "Skills:"]
    assert extractor.calls[0][1] is FileKind.PDF
    assert job_row(owner_session).status == "succeeded"
    detail = persona.client.get(f"/api/v1/resumes/{resume['id']}").json()
    assert detail["extraction_status"] == "succeeded"
    assert detail["parsed_outline"]["line_count"] == 5
    assert "extracted_text" not in detail


@pytest.mark.parametrize("error", list(ExtractionError))
def test_parse_failures_are_permanent_and_recorded(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
    error: ExtractionError,
) -> None:
    resume = upload(persona, synthetic_pdf("fail")).json()
    extractor = RecordingExtractor(ExtractionResult(error))
    runner = runner_with(app_sessions, db_settings, extractor)

    runner.run_once()
    again = runner.run_once()

    row = state(owner_session, resume["id"])
    assert row.extraction_status == "failed"
    assert row.extraction_error_code == error.value
    assert row.extracted_text is None
    assert row.parsed_outline is None
    job = job_row(owner_session)
    assert (job.status, job.attempts) == ("succeeded", 1)
    assert again is False
    assert len(extractor.calls) == 1
    summary = persona.client.get("/api/v1/resumes").json()[0]
    assert summary["extraction_status"] == "failed"
    assert summary["extraction_error_code"] == error.value


def test_infrastructure_errors_are_retried_not_marked_failed(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    resume = upload(persona, synthetic_pdf("retry")).json()
    runner = runner_with(app_sessions, db_settings, RecordingExtractor(OSError("disk")))

    runner.run_once()

    job = job_row(owner_session)
    assert (job.status, job.attempts, job.last_error_code) == ("queued", 1, "OSError")
    assert state(owner_session, resume["id"]).extraction_status == "pending"


def test_rerunning_a_succeeded_artifact_does_nothing(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    resume = upload(persona, synthetic_pdf("idempotent")).json()
    extractor = RecordingExtractor(success_result())
    runner_with(app_sessions, db_settings, extractor).run_once()
    artifact_id = owner_session.execute(text("SELECT id FROM artifacts")).scalar_one()
    handler = make_parse_resume_handler(
        FilesystemStorage(db_settings.artifact_storage_dir), db_settings, extractor
    )

    with app_sessions() as session:
        handler(
            JobContext(session, uuid.uuid4(), persona.user_id, None),
            ParseResumePayload(artifact_id=artifact_id, resume_id=uuid.UUID(resume["id"])),
        )
        session.commit()

    assert len(extractor.calls) == 1
    assert state(owner_session, resume["id"]).extraction_status == "succeeded"


def test_a_job_cannot_reach_another_users_artifact(
    app: FastAPI,
    idp: FakeIdentityProvider,
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    other = make_persona(app, idp, "b")
    victim = upload(persona, synthetic_pdf("victim")).json()
    own = upload(other, synthetic_pdf("own")).json()
    artifact_id = owner_session.execute(
        text("SELECT artifact_id FROM resumes WHERE id = :id"), {"id": victim["id"]}
    ).scalar_one()
    extractor = RecordingExtractor(success_result())
    handler = make_parse_resume_handler(
        FilesystemStorage(db_settings.artifact_storage_dir), db_settings, extractor
    )

    with app_sessions() as session:
        handler(
            JobContext(session, uuid.uuid4(), other.user_id, None),
            ParseResumePayload(artifact_id=artifact_id, resume_id=uuid.UUID(own["id"])),
        )
        handler(
            JobContext(session, uuid.uuid4(), other.user_id, None),
            ParseResumePayload(artifact_id=artifact_id, resume_id=uuid.UUID(victim["id"])),
        )
        session.commit()

    assert extractor.calls == []
    assert state(owner_session, victim["id"]).extraction_status == "pending"


def test_a_missing_target_is_a_no_op(
    persona: Persona, app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    extractor = RecordingExtractor(success_result())
    handler = make_parse_resume_handler(
        FilesystemStorage(db_settings.artifact_storage_dir), db_settings, extractor
    )

    with app_sessions() as session:
        handler(
            JobContext(session, uuid.uuid4(), persona.user_id, None),
            ParseResumePayload(artifact_id=uuid.uuid4(), resume_id=uuid.uuid4()),
        )

    assert extractor.calls == []


def test_a_missing_file_fails_the_extraction_permanently(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
) -> None:
    resume = upload(persona, synthetic_pdf("missing")).json()
    FilesystemStorage(db_settings.artifact_storage_dir).delete_prefix(f"users/{persona.user_id}/")
    extractor = RecordingExtractor(success_result())

    runner_with(app_sessions, db_settings, extractor).run_once()

    row = state(owner_session, resume["id"])
    assert (row.extraction_status, row.extraction_error_code) == ("failed", "unreadable")
    assert extractor.calls == []


@pytest.mark.parametrize(
    ("content", "filename", "headings"),
    [
        (synthetic_pdf("e2e-pdf"), "e2e.pdf", ["SUMMARY", "Experience", "Skills:", "Education"]),
        (synthetic_docx("e2e-docx"), "e2e.docx", ["Summary", "Work History", "Education"]),
    ],
    ids=["pdf", "docx"],
)
def test_worker_parses_real_files_in_a_child_process(
    persona: Persona,
    owner_session: Session,
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
    content: bytes,
    filename: str,
    headings: list[str],
) -> None:
    resume = upload(persona, content, filename).json()
    registry = JobRegistry()
    register_job_handlers(
        registry,
        DeletionHooks(),
        storage=FilesystemStorage(db_settings.artifact_storage_dir),
        settings=db_settings,
    )

    JobRunner(app_sessions, registry, db_settings, worker_id="e2e").run_once()

    row = state(owner_session, resume["id"])
    assert row.extraction_status == "succeeded"
    assert "Synthetic engineer" in row.extracted_text
    assert [s["heading"] for s in row.parsed_outline["sections"]] == headings
