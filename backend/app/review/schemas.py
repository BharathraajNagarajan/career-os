import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ProposalType, ReviewItem, ReviewSource, ReviewStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewItemResponse(BaseModel):
    id: uuid.UUID
    source: ReviewSource
    proposal_type: ProposalType
    proposed_payload: dict[str, Any]
    confidence: float | None
    rationale: str | None
    evidence_ref_id: uuid.UUID | None
    status: ReviewStatus
    decided_at: datetime | None
    decided_payload: dict[str, Any] | None
    decision_note: str | None
    state_version: int
    confirmable: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, item: ReviewItem, *, confirmable: bool) -> "ReviewItemResponse":
        return cls(
            id=item.id,
            source=item.source,
            proposal_type=item.proposal_type,
            proposed_payload=item.proposed_payload,
            confidence=None if item.confidence is None else float(item.confidence),
            rationale=item.rationale,
            evidence_ref_id=item.evidence_ref_id,
            status=item.status,
            decided_at=item.decided_at,
            decided_payload=item.decided_payload,
            decision_note=item.decision_note,
            state_version=item.state_version,
            confirmable=confirmable,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class ConfirmRequest(StrictModel):
    expected_state_version: int = Field(ge=1)


class EditConfirmRequest(ConfirmRequest):
    payload: dict[str, Any]


class RejectRequest(ConfirmRequest):
    note: str | None = Field(default=None, max_length=1000)
