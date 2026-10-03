import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ProposalType, ReviewSource
from app.profile.service import ProfileRepository
from app.review.handlers import ReviewContext, ReviewHandler, ReviewHandlerRegistry
from app.review.repository import ReviewItemRepository


class SkillNote(BaseModel):
    schema_version: int = 1
    name: str = Field(min_length=1, max_length=40)


@dataclass
class Recorder:
    calls: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    fail: bool = False


class RecordingRegistry(ReviewHandlerRegistry):
    def __init__(self, recorder: Recorder) -> None:
        super().__init__()
        self.recorder = recorder

        def confirm(context: ReviewContext, payload: SkillNote) -> None:
            profile = ProfileRepository(context.session).get_or_create(user_id=context.user_id)
            profile.headline = payload.name
            context.session.flush()
            recorder.calls.append((context.review_item_id, payload.name))
            if recorder.fail:
                raise RuntimeError("domain command failed")

        self.register(ReviewHandler(ProposalType.SKILL, SkillNote, confirm))


def recording_registry() -> RecordingRegistry:
    return RecordingRegistry(Recorder())


def create_item(
    factory: sessionmaker[Session],
    registry: ReviewHandlerRegistry,
    user_id: uuid.UUID,
    *,
    name: str = "Synthetic skill",
    proposal_type: ProposalType = ProposalType.SKILL,
    payload: dict[str, object] | None = None,
    llm_run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    with factory() as session:
        item = ReviewItemRepository(session).create(
            user_id=user_id,
            registry=registry,
            source=ReviewSource.EXTRACTION,
            proposal_type=proposal_type,
            payload=payload if payload is not None else SkillNote(name=name),
            confidence=Decimal("0.800"),
            rationale="Synthetic rationale",
            llm_run_id=llm_run_id,
        )
        session.commit()
        return item.id
