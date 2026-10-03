import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update

from app.db.models import LlmProviderName, LlmPurpose, LlmRun, LlmRunStatus, LlmTier
from app.db.tenancy import UserScopedRepository, require_user_id


def budget_day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def next_budget_reset(now: datetime) -> datetime:
    return budget_day_start(now) + timedelta(days=1)


def budget_lock_key(user_id: uuid.UUID) -> int:
    digest = hashlib.sha256(b"llm-budget:" + require_user_id(user_id).bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class LlmRunRepository(UserScopedRepository[LlmRun]):
    model = LlmRun

    def lock_budget(self, *, user_id: uuid.UUID) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": budget_lock_key(user_id)}
        )

    def spent_in_day(self, *, user_id: uuid.UUID, now: datetime) -> Decimal:
        start = budget_day_start(now)
        spent = self.session.execute(
            select(
                func.coalesce(func.sum(func.coalesce(LlmRun.cost_usd, LlmRun.reserved_cost_usd)), 0)
            ).where(
                LlmRun.user_id == require_user_id(user_id),
                LlmRun.created_at >= start,
                LlmRun.created_at < start + timedelta(days=1),
            )
        ).scalar_one()
        return Decimal(spent)

    def find_settled_structured(
        self,
        *,
        user_id: uuid.UUID,
        purpose: LlmPurpose,
        prompt_id: str,
        artifact_id: uuid.UUID,
        exclude_run_id: uuid.UUID | None,
    ) -> LlmRun | None:
        statement = (
            select(LlmRun)
            .where(
                LlmRun.user_id == require_user_id(user_id),
                LlmRun.purpose == purpose,
                LlmRun.prompt_id == prompt_id,
                LlmRun.status == LlmRunStatus.SUCCEEDED,
                LlmRun.context_manifest.contains(
                    {"entries": [{"entity_type": "artifact", "entity_id": str(artifact_id)}]}
                ),
            )
            .order_by(LlmRun.created_at.desc(), LlmRun.id.desc())
            .limit(1)
        )
        if exclude_run_id is not None:
            statement = statement.where(LlmRun.id != exclude_run_id)
        return self.session.scalars(statement).first()

    def create_reserved(
        self,
        *,
        user_id: uuid.UUID,
        purpose: LlmPurpose,
        prompt_id: str,
        prompt_version: int,
        provider: LlmProviderName,
        model: str,
        tier: LlmTier,
        max_output_tokens: int,
        reserved_cost_usd: Decimal,
        context_manifest: dict[str, Any],
        created_at: datetime,
        attempt: int = 1,
        repair_of_run_id: uuid.UUID | None = None,
    ) -> LlmRun:
        run = LlmRun(
            user_id=require_user_id(user_id),
            purpose=purpose,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            tier=tier,
            max_output_tokens=max_output_tokens,
            attempt=attempt,
            repair_of_run_id=repair_of_run_id,
            status=LlmRunStatus.RESERVED,
            reserved_cost_usd=reserved_cost_usd,
            context_manifest=context_manifest,
            created_at=created_at,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def settle(
        self,
        *,
        user_id: uuid.UUID,
        run_id: uuid.UUID,
        status: LlmRunStatus,
        cost_usd: Decimal,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int,
        error_code: str | None,
        output: dict[str, Any] | None,
        settled_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(LlmRun)
            .where(
                LlmRun.user_id == require_user_id(user_id),
                LlmRun.id == run_id,
                LlmRun.status == LlmRunStatus.RESERVED,
            )
            .values(
                status=status,
                cost_usd=cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                error_code=error_code,
                output=output,
                settled_at=settled_at,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1  # type: ignore[attr-defined, no-any-return]
