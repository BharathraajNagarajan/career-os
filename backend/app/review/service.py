import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import ReviewItem, ReviewStatus
from app.db.versioning import ConcurrencyConflict, update_versioned
from app.review.errors import InvalidPayload, NoHandler
from app.review.handlers import ReviewContext, ReviewHandlerRegistry
from app.review.repository import ReviewItemRepository
from app.review.transitions import ReviewAction, transition

log = get_logger(__name__)


class ReviewService:
    def __init__(self, session: Session, registry: ReviewHandlerRegistry) -> None:
        self.session = session
        self.registry = registry
        self.items = ReviewItemRepository(session)

    def list(
        self, *, user_id: uuid.UUID, status: ReviewStatus | None, limit: int
    ) -> Sequence[ReviewItem]:
        return self.items.list_for_user(user_id=user_id, status=status, limit=limit)

    def get(self, *, user_id: uuid.UUID, item_id: uuid.UUID) -> ReviewItem:
        return self.items.get(user_id=user_id, id=item_id)

    def confirm(
        self, *, user_id: uuid.UUID, item_id: uuid.UUID, expected_state_version: int
    ) -> ReviewItem:
        return self._confirm(user_id, item_id, expected_state_version, None)

    def edit_confirm(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_state_version: int,
        payload: Mapping[str, Any],
    ) -> ReviewItem:
        return self._confirm(user_id, item_id, expected_state_version, payload)

    def reject(
        self,
        *,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_state_version: int,
        note: str | None,
    ) -> ReviewItem:
        item = self._load(user_id, item_id, expected_state_version)
        target = transition(item.status, ReviewAction.REJECT)
        return self._decide(
            item,
            user_id,
            expected_state_version,
            values={"status": target, "decision_note": note},
        )

    def _load(self, user_id: uuid.UUID, item_id: uuid.UUID, expected: int) -> ReviewItem:
        item = self.items.get(user_id=user_id, id=item_id)
        if item.state_version != expected:
            raise ConcurrencyConflict("review_items")
        return item

    def _confirm(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        expected_state_version: int,
        edited: Mapping[str, Any] | None,
    ) -> ReviewItem:
        item = self._load(user_id, item_id, expected_state_version)
        target = transition(item.status, ReviewAction.CONFIRM)
        handler = self.registry.get(item.proposal_type)
        if handler is None:
            raise NoHandler(item.proposal_type.value)
        source = item.proposed_payload if edited is None else dict(edited)
        try:
            payload = handler.payload_model.model_validate(source)
        except ValidationError as exc:
            raise InvalidPayload(item.proposal_type.value) from exc
        context = ReviewContext(
            session=self.session,
            user_id=user_id,
            review_item_id=item.id,
            llm_run_id=item.llm_run_id,
        )
        return self._decide(
            item,
            user_id,
            expected_state_version,
            values={
                "status": target,
                "decided_payload": None if edited is None else payload.model_dump(mode="json"),
            },
            apply=lambda: handler.confirm(context, payload),
        )

    def _decide(
        self,
        item: ReviewItem,
        user_id: uuid.UUID,
        expected_state_version: int,
        *,
        values: dict[str, Any],
        apply: Callable[[], None] | None = None,
    ) -> ReviewItem:
        now = datetime.now(UTC)
        try:
            update_versioned(
                self.session,
                ReviewItem.__table__,  # type: ignore[arg-type]
                user_id=user_id,
                id=item.id,
                expected_version=expected_state_version,
                values={**values, "decided_at": now, "updated_at": now},
            )
            if apply is not None:
                apply()
            self.session.commit()
        except BaseException:
            self.session.rollback()
            raise
        self.session.refresh(item)
        log.info(
            "review_item_decided",
            user_id=str(user_id),
            review_item_id=str(item.id),
            proposal_type=item.proposal_type.value,
            status=item.status.value,
        )
        return item
