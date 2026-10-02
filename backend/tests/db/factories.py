import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import Actor, AggregateType, DomainEvent, User
from app.events.payloads import EventPayload, PayloadRegistry
from app.events.repository import DomainEventRepository

EVENT_TYPE = "test_noted"


class NotedPayload(EventPayload):
    schema_version: int = 1
    note_id: uuid.UUID


def noted_registry() -> PayloadRegistry:
    registry = PayloadRegistry()
    registry.register(EVENT_TYPE, NotedPayload, version=1)
    return registry


def make_user(session: Session) -> User:
    user = User(id=new_id(), primary_email=f"{new_id().hex}@example.test")
    session.add(user)
    session.flush()
    return user


def make_event(
    session: Session, user_id: uuid.UUID, *, voids_event_id: uuid.UUID | None = None
) -> DomainEvent:
    return DomainEventRepository(session).append(
        user_id=user_id,
        aggregate_type=AggregateType.OPPORTUNITY,
        aggregate_id=new_id(),
        event_type=EVENT_TYPE,
        occurred_at=datetime.now(UTC),
        actor=Actor.USER,
        payload=NotedPayload(note_id=new_id()),
        voids_event_id=voids_event_id,
        registry=noted_registry(),
    )
