import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.applications.repository import ApplicationRepository
from app.applications.timeline import TIMELINE_SOURCES, TimelineEntry
from app.db.models import AggregateType, DomainEvent, RecruitingAction


def action_event_source(
    session: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> list[TimelineEntry]:
    application_ids = ApplicationRepository(session).ids_for_opportunity(
        user_id=user_id, opportunity_id=opportunity_id
    )
    titles = {
        row.id: row.title
        for row in session.execute(
            select(RecruitingAction.id, RecruitingAction.title).where(
                RecruitingAction.user_id == user_id,
                or_(
                    RecruitingAction.opportunity_id == opportunity_id,
                    RecruitingAction.application_id.in_(application_ids),
                ),
            )
        )
    }
    if not titles:
        return []
    events = session.scalars(
        select(DomainEvent).where(
            DomainEvent.user_id == user_id,
            DomainEvent.aggregate_type == AggregateType.RECRUITING_ACTION,
            DomainEvent.aggregate_id.in_(list(titles)),
        )
    ).all()
    return [
        TimelineEntry(
            id=event.id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
            actor=event.actor,
            voided=False,
            voids_event_id=None,
            note=titles[event.aggregate_id],
            voidable=False,
        )
        for event in events
    ]


def register_action_event_source() -> None:
    if action_event_source not in TIMELINE_SOURCES:
        TIMELINE_SOURCES.append(action_event_source)
