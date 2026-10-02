import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from app.db.models import Actor, AggregateType, DomainEvent
from app.db.tenancy import UserScopedRepository, require_user_id
from app.events.payloads import EventPayload, PayloadRegistry, payload_registry


class DomainEventRepository(UserScopedRepository[DomainEvent]):
    model = DomainEvent

    def append(
        self,
        *,
        user_id: uuid.UUID,
        aggregate_type: AggregateType,
        aggregate_id: uuid.UUID,
        event_type: str,
        occurred_at: datetime,
        actor: Actor,
        payload: EventPayload,
        source_ref_id: uuid.UUID | None = None,
        voids_event_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        registry: PayloadRegistry = payload_registry,
    ) -> DomainEvent:
        event = DomainEvent(
            user_id=require_user_id(user_id),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            occurred_at=occurred_at,
            actor=actor,
            payload=registry.dump(event_type, payload),
            source_ref_id=source_ref_id,
            voids_event_id=voids_event_id,
            correlation_id=correlation_id,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_for_aggregate(
        self, *, user_id: uuid.UUID, aggregate_type: AggregateType, aggregate_id: uuid.UUID
    ) -> Sequence[DomainEvent]:
        owner = require_user_id(user_id)
        return self.session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.user_id == owner,
                DomainEvent.aggregate_type == aggregate_type,
                DomainEvent.aggregate_id == aggregate_id,
            )
            .order_by(DomainEvent.occurred_at, DomainEvent.recorded_at, DomainEvent.id)
        ).all()
