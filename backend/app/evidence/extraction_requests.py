import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import ExtractionStatus, Job, JobStatus, Resume, ResumeStatus
from app.db.tenancy import require_user_id
from app.evidence.extraction import (
    EXTRACT_EVIDENCE_JOB,
    ExtractEvidencePayload,
    extract_unique_key,
)
from app.evidence.schemas import EvidenceExtractionState
from app.jobs.queue import enqueue
from app.resumes.repository import ResumeRepository

NOT_REQUESTED = EvidenceExtractionState(status="not_requested", error_code=None)


def extraction_states(
    session: Session, *, user_id: uuid.UUID, resume_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, EvidenceExtractionState]:
    states = dict.fromkeys(resume_ids, NOT_REQUESTED)
    if not resume_ids:
        return states
    jobs = session.scalars(
        select(Job)
        .where(
            Job.user_id == require_user_id(user_id),
            Job.kind == EXTRACT_EVIDENCE_JOB,
            Job.payload["resume_id"].astext.in_([str(resume_id) for resume_id in resume_ids]),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    seen: set[uuid.UUID] = set()
    for job in jobs:
        resume_id = uuid.UUID(job.payload["resume_id"])
        if resume_id in seen:
            continue
        seen.add(resume_id)
        states[resume_id] = _state(job)
    return states


def _state(job: Job) -> EvidenceExtractionState:
    if job.status is JobStatus.SUCCEEDED:
        return EvidenceExtractionState(status="succeeded", error_code=None)
    if job.status is JobStatus.FAILED:
        return EvidenceExtractionState(status="failed", error_code=job.last_error_code)
    return EvidenceExtractionState(status="pending", error_code=None)


def enqueue_extraction(session: Session, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> None:
    enqueue(
        session,
        kind=EXTRACT_EVIDENCE_JOB,
        payload=ExtractEvidencePayload(resume_id=resume_id),
        user_id=user_id,
        unique_key=extract_unique_key(resume_id),
    )


def request_extraction(session: Session, *, user_id: uuid.UUID, resume_id: uuid.UUID) -> None:
    resume, artifact = ResumeRepository(session).get_with_artifact(user_id=user_id, id=resume_id)
    session.execute(
        select(Resume.id).where(Resume.user_id == user_id, Resume.id == resume.id).with_for_update()
    )
    if resume.status is ResumeStatus.ARCHIVED:
        raise ApiError(409, "resume_archived")
    if artifact.extraction_status is ExtractionStatus.PENDING:
        raise ApiError(409, "resume_not_parsed")
    if artifact.extraction_status is ExtractionStatus.FAILED:
        raise ApiError(422, "resume_unreadable")
    state = extraction_states(session, user_id=user_id, resume_ids=[resume.id])[resume.id]
    if state.status == "pending":
        raise ApiError(409, "extraction_pending")
    if state.status == "succeeded":
        raise ApiError(409, "extraction_exists")
    enqueue_extraction(session, user_id=user_id, resume_id=resume.id)
    session.commit()
