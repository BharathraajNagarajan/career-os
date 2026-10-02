import time
from dataclasses import dataclass
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.logging import get_logger
from app.jobs import queue
from app.jobs.queue import ClaimedJob
from app.jobs.registry import JobContext, JobRegistry

log = get_logger(__name__)


class JobOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


@dataclass
class JobRunner:
    sessions: sessionmaker[Session]
    registry: JobRegistry
    settings: Settings
    worker_id: str

    def run_once(self) -> bool:
        with self.sessions.begin() as session:
            queue.recover_stale(
                session, timeout_seconds=self.settings.job_visibility_timeout_seconds
            )
        with self.sessions.begin() as session:
            job = queue.claim(session, worker_id=self.worker_id)
        if job is None:
            return False
        self.process(job)
        return True

    def process(self, job: ClaimedJob) -> JobOutcome:
        started = time.perf_counter()
        fields = {
            "job_id": str(job.id),
            "job_kind": job.kind,
            "attempt": job.attempt,
            "user_id": None if job.user_id is None else str(job.user_id),
        }
        log.info("job_started", **fields)
        handler = self.registry.get(job.kind)
        if handler is None:
            return self._fail(job, "unknown_job_kind", fields)
        try:
            payload = handler.payload_model.model_validate(job.payload)
        except ValidationError:
            return self._fail(job, "invalid_payload", fields)
        try:
            with self.sessions() as session:
                context = JobContext(session, job.id, job.user_id, job.correlation_id)
                handler.handle(context, payload)
                if not queue.mark_succeeded(session, job, worker_id=self.worker_id):
                    session.rollback()
                    log.warning("job_lease_lost", **fields)
                    return JobOutcome.LEASE_LOST
                session.commit()
        except Exception as exc:
            return self._retry_or_fail(job, type(exc).__name__, fields)
        log.info(
            "job_succeeded",
            **fields,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return JobOutcome.SUCCEEDED

    def _retry_or_fail(
        self, job: ClaimedJob, error_code: str, fields: dict[str, object]
    ) -> JobOutcome:
        if job.attempt >= job.max_attempts:
            return self._fail(job, error_code, fields)
        delay = queue.backoff_seconds(
            job.attempt,
            base=self.settings.job_backoff_base_seconds,
            cap=self.settings.job_backoff_max_seconds,
        )
        with self.sessions.begin() as session:
            queue.schedule_retry(
                session, job, worker_id=self.worker_id, error_code=error_code, delay_seconds=delay
            )
        log.warning("job_retry_scheduled", **fields, error_code=error_code)
        return JobOutcome.RETRY_SCHEDULED

    def _fail(self, job: ClaimedJob, error_code: str, fields: dict[str, object]) -> JobOutcome:
        with self.sessions.begin() as session:
            queue.mark_failed(session, job, worker_id=self.worker_id, error_code=error_code)
        log.error("job_failed", **fields, error_code=error_code)
        return JobOutcome.FAILED
