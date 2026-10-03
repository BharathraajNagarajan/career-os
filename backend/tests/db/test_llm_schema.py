import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import LlmProviderName, LlmPurpose, LlmRun, LlmRunStatus, LlmTier
from app.llm.repository import LlmRunRepository
from tests.db.factories import make_user
from tests.db.llm_helpers import VALID, make_gateway, structured
from tests.db.review_helpers import create_item, recording_registry
from tests.db.test_roles import assert_denied

pytestmark = pytest.mark.db


def reserved_run(session: Session, user_id: uuid.UUID, **overrides: object) -> LlmRun:
    values: dict[str, object] = {
        "user_id": user_id,
        "purpose": LlmPurpose.CHAT,
        "prompt_id": "unit.prompt",
        "prompt_version": 1,
        "provider": LlmProviderName.FAKE,
        "model": "fake-fast",
        "tier": LlmTier.FAST,
        "max_output_tokens": 100,
        "status": LlmRunStatus.RESERVED,
        "reserved_cost_usd": Decimal("0.001"),
        "context_manifest": {"schema_version": 1, "entries": []},
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    run = LlmRun(**values)
    session.add(run)
    session.flush()
    return run


@pytest.fixture
def user_id(session: Session) -> uuid.UUID:
    user = make_user(session)
    session.commit()
    return user.id


def test_app_role_cannot_delete_or_truncate_llm_runs(session: Session, user_id: uuid.UUID) -> None:
    reserved_run(session, user_id)
    session.commit()

    assert_denied(session, "DELETE FROM llm_runs")
    assert_denied(session, "TRUNCATE llm_runs")


@pytest.mark.parametrize(
    "assignment",
    [
        "prompt_id = 'changed'",
        "model = 'changed'",
        "reserved_cost_usd = 0",
        "context_manifest = '{}'::jsonb",
        "created_at = now()",
        "user_id = gen_random_uuid()",
        "attempt = 2",
        "max_output_tokens = 1",
    ],
)
def test_app_role_cannot_rewrite_the_immutable_parts_of_a_run(
    session: Session, user_id: uuid.UUID, assignment: str
) -> None:
    reserved_run(session, user_id)
    session.commit()

    assert_denied(session, "UPDATE llm_runs SET " + assignment)  # noqa: S608


def test_settlement_can_only_happen_once(session: Session, user_id: uuid.UUID) -> None:
    run = reserved_run(session, user_id)
    repository = LlmRunRepository(session)

    def settle(cost: str) -> bool:
        return repository.settle(
            user_id=user_id,
            run_id=run.id,
            status=LlmRunStatus.SUCCEEDED,
            cost_usd=Decimal(cost),
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            error_code=None,
            output=None,
            settled_at=datetime.now(UTC),
        )

    assert settle("0.0005") is True
    assert settle("0.0001") is False
    session.commit()
    stored = session.execute(select(LlmRun.cost_usd).where(LlmRun.id == run.id)).scalar_one()
    assert stored == Decimal("0.000500")


def test_settlement_never_touches_another_users_run(session: Session, user_id: uuid.UUID) -> None:
    other = make_user(session)
    run = reserved_run(session, other.id)

    changed = LlmRunRepository(session).settle(
        user_id=user_id,
        run_id=run.id,
        status=LlmRunStatus.FAILED,
        cost_usd=Decimal(0),
        input_tokens=None,
        output_tokens=None,
        latency_ms=0,
        error_code="x",
        output=None,
        settled_at=datetime.now(UTC),
    )

    assert changed is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": LlmRunStatus.SUCCEEDED},
        {"status": LlmRunStatus.RESERVED, "cost_usd": Decimal("0.1")},
        {"status": LlmRunStatus.RESERVED, "settled_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"attempt": 3},
        {"attempt": 2},
        {"max_output_tokens": 0},
        {"reserved_cost_usd": Decimal("-1")},
        {"context_manifest": []},
    ],
)
def test_the_database_rejects_inconsistent_runs(
    session: Session, user_id: uuid.UUID, overrides: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        reserved_run(session, user_id, **overrides)
    session.rollback()


def test_a_repair_run_must_link_to_a_run_of_the_same_user(
    session: Session, user_id: uuid.UUID
) -> None:
    other = make_user(session)
    foreign = reserved_run(session, other.id)
    session.commit()

    with pytest.raises(IntegrityError):
        reserved_run(session, user_id, attempt=2, repair_of_run_id=foreign.id)
    session.rollback()


@pytest.mark.parametrize(
    ("purpose", "provider", "tier"),
    [("anything", "fake", "fast"), ("chat", "other", "fast"), ("chat", "fake", "slow")],
)
def test_purpose_provider_and_tier_come_from_closed_lists(
    session: Session, user_id: uuid.UUID, purpose: str, provider: str, tier: str
) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO llm_runs (id, user_id, purpose, prompt_id, prompt_version, provider, "
                "model, tier, max_output_tokens, status, reserved_cost_usd, context_manifest, "
                "created_at) VALUES (gen_random_uuid(), :user, :purpose, 'p', 1, :provider, 'm', "
                ":tier, 1, 'reserved', 0, '{}'::jsonb, now())"
            ),
            {"user": user_id, "purpose": purpose, "provider": provider, "tier": tier},
        )
    session.rollback()


def test_account_deletion_removes_runs_and_review_items(
    app_sessions: sessionmaker[Session],
    session: Session,
    owner_session: Session,
    user_id: uuid.UUID,
) -> None:
    gateway, _ = make_gateway(app_sessions, script=[VALID])
    run_id = structured(gateway, user_id).run_id
    create_item(app_sessions, recording_registry(), user_id, llm_run_id=run_id)
    owner_session.execute(
        text("UPDATE users SET status = 'deletion_requested' WHERE id = :id"), {"id": user_id}
    )
    owner_session.commit()

    deleted: bool = session.execute(select(func.public.delete_user_account(user_id))).scalar_one()
    session.commit()

    assert deleted is True
    for table in ("llm_runs", "review_items"):
        remaining: int = owner_session.execute(
            text(f"SELECT count(*) FROM {table}")  # noqa: S608
        ).scalar_one()
        assert remaining == 0
