import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.db.models import ProposalType, ReviewItem, ReviewSource, ReviewStatus
from app.db.tenancy import UserScopedRepository, require_user_id
from app.review.errors import InvalidPayload
from app.review.handlers import ReviewHandlerRegistry


class ReviewItemRepository(UserScopedRepository[ReviewItem]):
    model = ReviewItem

    def create(
        self,
        *,
        user_id: uuid.UUID,
        registry: ReviewHandlerRegistry,
        source: ReviewSource,
        proposal_type: ProposalType,
        payload: BaseModel | Mapping[str, Any],
        confidence: Decimal | None = None,
        rationale: str | None = None,
        evidence_ref_id: uuid.UUID | None = None,
        llm_run_id: uuid.UUID | None = None,
    ) -> ReviewItem:
        stored = self._validated_payload(registry, proposal_type, payload)
        item = ReviewItem(
            user_id=require_user_id(user_id),
            source=source,
            proposal_type=proposal_type,
            proposed_payload=stored,
            confidence=confidence,
            rationale=rationale,
            evidence_ref_id=evidence_ref_id,
            llm_run_id=llm_run_id,
        )
        self.session.add(item)
        self.session.flush()
        self.session.refresh(item)
        return item

    def list_for_user(
        self, *, user_id: uuid.UUID, status: ReviewStatus | None = None, limit: int = 100
    ) -> Sequence[ReviewItem]:
        statement = select(ReviewItem).where(ReviewItem.user_id == require_user_id(user_id))
        if status is not None:
            statement = statement.where(ReviewItem.status == status)
        return self.session.scalars(
            statement.order_by(ReviewItem.created_at.desc(), ReviewItem.id.desc()).limit(limit)
        ).all()

    @staticmethod
    def _validated_payload(
        registry: ReviewHandlerRegistry,
        proposal_type: ProposalType,
        payload: BaseModel | Mapping[str, Any],
    ) -> dict[str, Any]:
        handler = registry.get(proposal_type)
        raw: dict[str, Any] = (
            payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
        )
        if handler is not None:
            try:
                validated: dict[str, Any] = handler.payload_model.model_validate(raw).model_dump(
                    mode="json"
                )
            except ValidationError as exc:
                raise InvalidPayload(proposal_type.value) from exc
            return validated
        if not isinstance(raw.get("schema_version"), int):
            raise InvalidPayload("payload needs an integer schema_version")
        return raw
