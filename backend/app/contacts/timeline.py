import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.applications.repository import ApplicationRepository
from app.applications.timeline import TIMELINE_SOURCES, TimelineEntry
from app.db.models import Actor, AggregateType, Interaction


def interaction_source(
    session: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> list[TimelineEntry]:
    application_ids = ApplicationRepository(session).ids_for_opportunity(
        user_id=user_id, opportunity_id=opportunity_id
    )
    rows = session.scalars(
        select(Interaction).where(
            Interaction.user_id == user_id,
            or_(
                Interaction.opportunity_id == opportunity_id,
                Interaction.application_id.in_(application_ids),
            ),
        )
    ).all()
    return [
        TimelineEntry(
            id=row.id,
            aggregate_type=AggregateType.CONTACT,
            aggregate_id=row.contact_id,
            event_type="INTERACTION",
            occurred_at=row.occurred_at,
            recorded_at=row.created_at,
            actor=Actor.USER,
            voided=False,
            voids_event_id=None,
            note=row.summary,
            voidable=False,
            interaction_channel=row.channel.value,
            interaction_direction=row.direction.value,
        )
        for row in rows
    ]


def register_interaction_source() -> None:
    if interaction_source not in TIMELINE_SOURCES:
        TIMELINE_SOURCES.append(interaction_source)
