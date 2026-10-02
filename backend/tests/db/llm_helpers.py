import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import ModelPrice
from app.db.models import LlmProviderName, LlmPurpose, LlmRun, LlmTier
from app.llm.config import LlmConfig
from app.llm.gateway import Clock, ModelGateway, ModelStream, StructuredResult, utc_now
from app.llm.prompts.catalog import (
    SELFTEST_STREAM,
    SELFTEST_STRUCTURED,
    NoteTone,
    default_registry,
)
from app.llm.providers.fake import FakeProvider, Scripted
from app.llm.schemas import ManifestEntry

PRICE = ModelPrice(input_usd_per_mtok=Decimal("1"), output_usd_per_mtok=Decimal("5"))
NOTE = "A synthetic note about a pleasant afternoon walk."
VALID = json.dumps({"tone": "positive", "summary": "A pleasant walk."})
INVALID = json.dumps({"tone": "ecstatic", "summary": "Too happy."})


def make_config(cap: str = "1.00") -> LlmConfig:
    return LlmConfig(
        provider=LlmProviderName.FAKE,
        models={LlmTier.FAST: "fake-fast", LlmTier.REASONING: "fake-reasoning"},
        prices={"fake-fast": PRICE, "fake-reasoning": PRICE},
        daily_cap_usd=Decimal(cap),
        timeout_seconds=5.0,
    )


def make_gateway(
    factory: sessionmaker[Session],
    *,
    cap: str = "1.00",
    script: Iterable[Scripted] = (),
    provider: FakeProvider | None = None,
    clock: Clock = utc_now,
) -> tuple[ModelGateway, FakeProvider]:
    fake = provider or FakeProvider(script)
    gateway = ModelGateway(
        session_factory=factory,
        provider=fake,
        config=make_config(cap),
        prompts=default_registry(),
        clock=clock,
    )
    return gateway, fake


def structured(
    gateway: ModelGateway,
    user_id: uuid.UUID,
    *,
    note: str = NOTE,
    max_output_tokens: int = 200,
    manifest: Iterable[ManifestEntry] = (),
) -> StructuredResult[NoteTone]:
    return gateway.structured(
        user_id=user_id,
        purpose=LlmPurpose.CLASSIFY_EMAIL,
        prompt_id=SELFTEST_STRUCTURED,
        tier=LlmTier.FAST,
        output_type=NoteTone,
        variables={"note": note},
        context_manifest=list(manifest),
        max_output_tokens=max_output_tokens,
    )


def open_stream(
    gateway: ModelGateway, user_id: uuid.UUID, *, question: str = "How are you?"
) -> ModelStream:
    return gateway.stream(
        user_id=user_id,
        purpose=LlmPurpose.CHAT,
        prompt_id=SELFTEST_STREAM,
        tier=LlmTier.FAST,
        variables={"question": question},
        context_manifest=[],
        max_output_tokens=200,
    )


def runs_for(session: Session, user_id: uuid.UUID) -> list[LlmRun]:
    session.rollback()
    return list(
        session.scalars(
            select(LlmRun)
            .where(LlmRun.user_id == user_id)
            .order_by(LlmRun.created_at, LlmRun.attempt)
            .execution_options(populate_existing=True)
        )
    )


def fixed_clock(moment: datetime) -> Clock:
    return lambda: moment.astimezone(UTC)
