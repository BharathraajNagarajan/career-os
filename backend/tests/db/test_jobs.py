import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.ids import new_id
from app.db.models import DomainEvent, Job, JobStatus
from app.events.repository import DomainEventRepository
from app.jobs import queue
from app.jobs.registry import JobContext, JobRegistry
from app.jobs.runner import JobOutcome, JobRunner
from tests.db.factories import make_event, make_user

pytestmark = pytest.mark.db

ReadLogs = Callable[[], list[dict[str, object]]]


class EventRef(BaseModel):
    event_id: uuid.UUID


def load_job(sessions: sessionmaker[Session], job_id: uuid.UUID) -> Job:
    with sessions() as session:
        return session.get_one(Job, job_id)


def runner_for(
    sessions: sessionmaker[Session], settings: Settings, registry: JobRegistry
) -> JobRunner:
    return JobRunner(sessions, registry, settings, worker_id="test-worker")


def failing_registry() -> JobRegistry:
    def explode(ctx: JobContext, payload: EventRef) -> None:
        raise RuntimeError("contains user content that must not be stored")

    registry = JobRegistry()
    registry.register("explode", EventRef, explode)
    return registry


def enqueue_committed(
    sessions: sessionmaker[Session],
    *,
    unique_key: str | None = None,
    run_after: datetime | None = None,
) -> uuid.UUID:
    with sessions.begin() as session:
        return queue.enqueue(
            session,
            kind="explode",
            payload=EventRef(event_id=new_id()),
            user_id=None,
            unique_key=unique_key,
            run_after=run_after,
        )


def test_enqueue_rolls_back_with_its_transaction(app_sessions: sessionmaker[Session]) -> None:
    with app_sessions() as session:
        job_id = queue.enqueue(
            session, kind="noop", payload=EventRef(event_id=new_id()), user_id=None
        )
        session.rollback()

    with app_sessions() as session:
        assert session.get(Job, job_id) is None


def test_unique_key_deduplicates_active_jobs(app_sessions: sessionmaker[Session]) -> None:
    first = enqueue_committed(app_sessions, unique_key="sync:1")
    second = enqueue_committed(app_sessions, unique_key="sync:1")
    other = enqueue_committed(app_sessions, unique_key="sync:2")

    assert first == second
    assert other != first
    with app_sessions() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 2


def test_unique_key_is_free_again_after_the_job_finishes(
    app_sessions: sessionmaker[Session],
) -> None:
    first = enqueue_committed(app_sessions, unique_key="sync:1")
    with app_sessions.begin() as session:
        session.execute(update(Job).values(status=JobStatus.SUCCEEDED))

    assert enqueue_committed(app_sessions, unique_key="sync:1") != first


def test_claim_skips_jobs_scheduled_in_the_future(app_sessions: sessionmaker[Session]) -> None:
    enqueue_committed(app_sessions, run_after=datetime.now(UTC) + timedelta(hours=1))

    with app_sessions.begin() as session:
        assert queue.claim(session, worker_id="w") is None


def test_claim_skips_rows_locked_by_another_claimer(app_sessions: sessionmaker[Session]) -> None:
    first = enqueue_committed(app_sessions)
    second = enqueue_committed(app_sessions)

    with app_sessions.begin() as holder, app_sessions.begin() as other:
        held = queue.claim(holder, worker_id="a")
        skipped_to = queue.claim(other, worker_id="b")
        nothing_left = queue.claim(other, worker_id="b")

    assert held is not None
    assert skipped_to is not None
    assert {held.id, skipped_to.id} == {first, second}
    assert nothing_left is None


def test_concurrent_claimers_never_claim_the_same_job(
    app_sessions: sessionmaker[Session],
) -> None:
    expected = {enqueue_committed(app_sessions) for _ in range(40)}
    claimed: dict[str, list[uuid.UUID]] = {"a": [], "b": [], "c": []}
    start = threading.Barrier(len(claimed))

    def claimer(name: str) -> None:
        start.wait()
        while True:
            with app_sessions.begin() as session:
                job = queue.claim(session, worker_id=name)
            if job is None:
                return
            claimed[name].append(job.id)

    threads = [threading.Thread(target=claimer, args=(name,)) for name in claimed]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    all_claims = [job_id for ids in claimed.values() for job_id in ids]
    assert len(all_claims) == len(set(all_claims))
    assert set(all_claims) == expected


def test_failure_schedules_retry_with_backoff(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    job_id = enqueue_committed(app_sessions)
    runner = runner_for(app_sessions, db_settings, failing_registry())

    assert runner.run_once() is True

    job = load_job(app_sessions, job_id)
    with app_sessions() as session:
        now = session.scalar(select(func.now()))
    assert now is not None
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 1
    assert job.last_error_code == "RuntimeError"
    assert job.locked_by is None
    delay = (job.run_after - now).total_seconds()
    assert (
        db_settings.job_backoff_base_seconds / 2 - 1
        <= delay
        <= db_settings.job_backoff_base_seconds
    )
    assert runner.run_once() is False


def test_last_attempt_marks_job_failed(
    app_sessions: sessionmaker[Session], db_settings: Settings, read_logs: ReadLogs
) -> None:
    job_id = enqueue_committed(app_sessions)
    with app_sessions.begin() as session:
        session.execute(update(Job).values(max_attempts=2, attempts=1))

    runner_for(app_sessions, db_settings, failing_registry()).run_once()

    job = load_job(app_sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.attempts == 2
    assert job.finished_at is not None
    failed = [entry for entry in read_logs() if entry["event"] == "job_failed"]
    assert failed[0]["error_code"] == "RuntimeError"
    assert "user content" not in str(read_logs())


@pytest.mark.parametrize(
    ("kind", "payload", "error_code"),
    [
        ("unregistered", {"event_id": str(uuid.uuid4())}, "unknown_job_kind"),
        ("explode", {"wrong": "shape"}, "invalid_payload"),
    ],
)
def test_unknown_kind_and_invalid_payload_fail_permanently(
    app_sessions: sessionmaker[Session],
    db_settings: Settings,
    kind: str,
    payload: dict[str, str],
    error_code: str,
) -> None:
    with app_sessions.begin() as session:
        session.add(Job(id=(job_id := new_id()), kind=kind, payload=payload))

    runner_for(app_sessions, db_settings, failing_registry()).run_once()

    job = load_job(app_sessions, job_id)
    assert job.status is JobStatus.FAILED
    assert job.last_error_code == error_code
    assert job.attempts == 1


def test_handler_work_commits_with_success(
    app_sessions: sessionmaker[Session], db_settings: Settings, read_logs: ReadLogs
) -> None:
    with app_sessions.begin() as session:
        user_id = make_user(session).id
        source_id = make_event(session, user_id).id
    voided: list[uuid.UUID] = []

    def void_event(ctx: JobContext, payload: EventRef) -> None:
        original = DomainEventRepository(ctx.session).get(
            user_id=ctx.require_user_id(), id=payload.event_id
        )
        voided.append(make_event(ctx.session, original.user_id, voids_event_id=original.id).id)

    registry = JobRegistry()
    registry.register("void", EventRef, void_event)
    with app_sessions.begin() as session:
        job_id = queue.enqueue(
            session, kind="void", payload=EventRef(event_id=source_id), user_id=user_id
        )

    assert runner_for(app_sessions, db_settings, registry).run_once() is True

    assert load_job(app_sessions, job_id).status is JobStatus.SUCCEEDED
    with app_sessions() as session:
        assert session.get(DomainEvent, voided[0]) is not None
    succeeded = [entry for entry in read_logs() if entry["event"] == "job_succeeded"]
    assert succeeded[0]["user_id"] == str(user_id)
    assert "dropped_field_count" not in succeeded[0]


def test_handler_failure_rolls_back_its_work(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    with app_sessions.begin() as session:
        user_id = make_user(session).id

    def write_then_fail(ctx: JobContext, payload: EventRef) -> None:
        make_event(ctx.session, ctx.require_user_id())
        raise RuntimeError

    registry = JobRegistry()
    registry.register("write_then_fail", EventRef, write_then_fail)
    with app_sessions.begin() as session:
        queue.enqueue(
            session, kind="write_then_fail", payload=EventRef(event_id=new_id()), user_id=user_id
        )

    runner_for(app_sessions, db_settings, registry).run_once()

    with app_sessions() as session:
        assert session.scalar(select(func.count()).select_from(DomainEvent)) == 0


def test_handler_cannot_load_another_users_entity(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    with app_sessions.begin() as session:
        attacker = make_user(session).id
        victim = make_user(session).id
        victims_event = make_event(session, victim).id
    seen: list[DomainEvent] = []

    def read_event(ctx: JobContext, payload: EventRef) -> None:
        seen.append(
            DomainEventRepository(ctx.session).get(
                user_id=ctx.require_user_id(), id=payload.event_id
            )
        )

    registry = JobRegistry()
    registry.register("read", EventRef, read_event)
    with app_sessions.begin() as session:
        job_id = queue.enqueue(
            session, kind="read", payload=EventRef(event_id=victims_event), user_id=attacker
        )

    assert runner_for(app_sessions, db_settings, registry).run_once() is True

    assert seen == []
    assert load_job(app_sessions, job_id).last_error_code == "NotFound"


def test_stale_running_jobs_are_recovered(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    job_id = enqueue_committed(app_sessions)
    with app_sessions.begin() as session:
        crashed = queue.claim(session, worker_id="crashed-worker")
    assert crashed is not None

    with app_sessions.begin() as session:
        assert queue.recover_stale(session, timeout_seconds=60) == 0
        session.execute(update(Job).values(locked_at=func.now() - timedelta(seconds=120)))
    with app_sessions.begin() as session:
        assert queue.recover_stale(session, timeout_seconds=60) == 1

    job = load_job(app_sessions, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.locked_by is None
    assert job.last_error_code == "visibility_timeout"


def test_recovered_job_cannot_be_completed_by_the_old_worker(
    app_sessions: sessionmaker[Session], db_settings: Settings
) -> None:
    enqueue_committed(app_sessions)
    with app_sessions.begin() as session:
        stale = queue.claim(session, worker_id="slow-worker")
    assert stale is not None
    with app_sessions.begin() as session:
        session.execute(update(Job).values(locked_at=func.now() - timedelta(seconds=120)))
        queue.recover_stale(session, timeout_seconds=60)
    with app_sessions.begin() as session:
        assert queue.claim(session, worker_id="fresh-worker") is not None

    slow = JobRunner(app_sessions, JobRegistry(), db_settings, worker_id="slow-worker")
    slow.registry.register("explode", EventRef, lambda ctx, payload: None)

    assert slow.process(stale) is JobOutcome.LEASE_LOST
