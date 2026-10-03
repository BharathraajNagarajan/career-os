import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.applications.repository import ApplicationRepository, event_record
from app.db.models import Actor, AggregateType, DomainEvent, Opportunity
from app.db.tenancy import resolve_owned
from app.events.payloads import payload_registry
from app.events.repository import DomainEventRepository
from app.state_machines.application import ApplicationState, is_voidable, voided_ids


@dataclass(frozen=True)
class TimelineEntry:
    id: uuid.UUID
    aggregate_type: AggregateType
    aggregate_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    recorded_at: datetime
    actor: Actor
    voided: bool
    voids_event_id: uuid.UUID | None
    note: str | None
    voidable: bool

    @property
    def order_key(self) -> tuple[datetime, datetime, uuid.UUID]:
        return (self.occurred_at, self.recorded_at, self.id)


TimelineSource = Callable[[Session, uuid.UUID, uuid.UUID], list[TimelineEntry]]


def entry_note(event: DomainEvent) -> str | None:
    payload = payload_registry.load(event.event_type, event.payload)
    text = getattr(payload, "note", None) or getattr(payload, "reason", None)
    return text if isinstance(text, str) else None


def domain_event_source(
    session: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> list[TimelineEntry]:
    events = DomainEventRepository(session)
    opportunity_events = events.list_for_aggregate(
        user_id=user_id, aggregate_type=AggregateType.OPPORTUNITY, aggregate_id=opportunity_id
    )
    by_application = {
        application_id: events.list_for_aggregate(
            user_id=user_id, aggregate_type=AggregateType.APPLICATION, aggregate_id=application_id
        )
        for application_id in ApplicationRepository(session).ids_for_opportunity(
            user_id=user_id, opportunity_id=opportunity_id
        )
    }
    entries = [_entry(event, voided=False, voidable=False) for event in opportunity_events]
    for application_events in by_application.values():
        state = ApplicationState([event_record(event) for event in application_events])
        gone = voided_ids(state.events)
        records = {record.id: record for record in state.events}
        entries.extend(
            _entry(
                event,
                voided=event.id in gone,
                voidable=is_voidable(state, records[event.id]),
            )
            for event in application_events
        )
    return entries


def _entry(event: DomainEvent, *, voided: bool, voidable: bool) -> TimelineEntry:
    return TimelineEntry(
        id=event.id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        actor=event.actor,
        voided=voided,
        voids_event_id=event.voids_event_id,
        note=entry_note(event),
        voidable=voidable,
    )


TIMELINE_SOURCES: list[TimelineSource] = [domain_event_source]


def build_timeline(
    session: Session, *, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> list[TimelineEntry]:
    resolve_owned(session, Opportunity, user_id=user_id, id=opportunity_id)
    entries = [
        entry for source in TIMELINE_SOURCES for entry in source(session, user_id, opportunity_id)
    ]
    return sorted(entries, key=lambda entry: entry.order_key)
