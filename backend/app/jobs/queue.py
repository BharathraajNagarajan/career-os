import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import ACTIVE_JOB_STATUSES, Job, JobStatus


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    correlation_id: uuid.UUID | None


def enqueue(
    session: Session,
    *,
    kind: str,
    payload: BaseModel,
    user_id: uuid.UUID | None,
    unique_key: str | None = None,
    run_after: datetime | None = None,
    correlation_id: uuid.UUID | None = None,
) -> uuid.UUID:
    values: dict[str, Any] = {
        "id": new_id(),
        "kind": kind,
        "payload": payload.model_dump(mode="json"),
        "user_id": user_id,
        "unique_key": unique_key,
        "correlation_id": correlation_id,
    }
    if run_after is not None:
        values["run_after"] = run_after
    statement = insert(Job).values(values)
    if unique_key is None:
        session.execute(statement)
        return uuid.UUID(str(values["id"]))
    deduplicated = statement.on_conflict_do_nothing(
        index_elements=[Job.unique_key], index_where=Job.status.in_(ACTIVE_JOB_STATUSES)
    ).returning(Job.id)
    active = select(Job.id).where(Job.unique_key == unique_key, Job.status.in_(ACTIVE_JOB_STATUSES))
    for _ in range(3):
        job_id = session.execute(deduplicated).scalar_one_or_none()
        if job_id is None:
            job_id = session.execute(active).scalar_one_or_none()
        if job_id is not None:
            return job_id
    raise RuntimeError("enqueue_conflict")


def claim(session: Session, *, worker_id: str) -> ClaimedJob | None:
    next_job = (
        select(Job.id)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= func.now())
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    row = session.execute(
        update(Job)
        .where(Job.id == next_job)
        .values(
            status=JobStatus.RUNNING,
            locked_by=worker_id,
            locked_at=func.now(),
            attempts=Job.attempts + 1,
            updated_at=func.now(),
        )
        .returning(
            Job.id,
            Job.kind,
            Job.user_id,
            Job.payload,
            Job.attempts,
            Job.max_attempts,
            Job.correlation_id,
        )
        .execution_options(synchronize_session=False)
    ).one_or_none()
    return None if row is None else ClaimedJob(*row)


def _owned_by(job: ClaimedJob, worker_id: str) -> Any:
    return (
        (Job.id == job.id)
        & (Job.status == JobStatus.RUNNING)
        & (Job.locked_by == worker_id)
        & (Job.attempts == job.attempt)
    )


def mark_succeeded(session: Session, job: ClaimedJob, *, worker_id: str) -> bool:
    result = session.execute(
        update(Job)
        .where(_owned_by(job, worker_id))
        .values(
            status=JobStatus.SUCCEEDED,
            locked_by=None,
            locked_at=None,
            finished_at=func.now(),
            updated_at=func.now(),
        )
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


def mark_failed(session: Session, job: ClaimedJob, *, worker_id: str, error_code: str) -> bool:
    result = session.execute(
        update(Job)
        .where(_owned_by(job, worker_id))
        .values(
            status=JobStatus.FAILED,
            last_error_code=error_code,
            locked_by=None,
            locked_at=None,
            finished_at=func.now(),
            updated_at=func.now(),
        )
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


def schedule_retry(
    session: Session, job: ClaimedJob, *, worker_id: str, error_code: str, delay_seconds: float
) -> bool:
    result = session.execute(
        update(Job)
        .where(_owned_by(job, worker_id))
        .values(
            status=JobStatus.QUEUED,
            last_error_code=error_code,
            run_after=func.now() + timedelta(seconds=delay_seconds),
            locked_by=None,
            locked_at=None,
            updated_at=func.now(),
        )
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


def recover_stale(session: Session, *, timeout_seconds: float) -> int:
    exhausted = Job.attempts >= Job.max_attempts
    result = session.execute(
        update(Job)
        .where(
            Job.status == JobStatus.RUNNING,
            Job.locked_at < func.now() - timedelta(seconds=timeout_seconds),
        )
        .values(
            status=case((exhausted, JobStatus.FAILED.value), else_=JobStatus.QUEUED.value),
            finished_at=case((exhausted, func.now()), else_=None),
            last_error_code="visibility_timeout",
            run_after=func.now(),
            locked_by=None,
            locked_at=None,
            updated_at=func.now(),
        )
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


def backoff_seconds(
    attempt: int, *, base: float, cap: float, rng: random.Random | None = None
) -> float:
    ceiling = min(cap, base * 2 ** (attempt - 1))
    return (rng or random).uniform(ceiling / 2, ceiling)
