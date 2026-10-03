import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import ProposalType


@dataclass(frozen=True)
class ReviewContext:
    session: Session
    user_id: uuid.UUID
    review_item_id: uuid.UUID
    llm_run_id: uuid.UUID | None


@dataclass(frozen=True)
class ReviewHandler[P: BaseModel]:
    proposal_type: ProposalType
    payload_model: type[P]
    confirm: Callable[[ReviewContext, P], None]


class ReviewHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[ProposalType, ReviewHandler[Any]] = {}

    def register(self, handler: ReviewHandler[Any]) -> None:
        if handler.proposal_type in self._handlers:
            raise ValueError(f"handler already registered for {handler.proposal_type.value}")
        self._handlers[handler.proposal_type] = handler

    def get(self, proposal_type: ProposalType) -> ReviewHandler[Any] | None:
        return self._handlers.get(proposal_type)
