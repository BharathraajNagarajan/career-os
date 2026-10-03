import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Actor, AggregateType
from app.events.payloads import EventPayload, payload_registry
from app.events.repository import DomainEventRepository

OPPORTUNITY_INGESTED = "OPPORTUNITY_INGESTED"
OPPORTUNITY_EXTRACTED = "OPPORTUNITY_EXTRACTED"
OPPORTUNITY_CONTENT_EDITED = "OPPORTUNITY_CONTENT_EDITED"
OPPORTUNITY_PRIORITY_CHANGED = "OPPORTUNITY_PRIORITY_CHANGED"
COMPANY_CREATED = "COMPANY_CREATED"
COMPANY_PRIORITY_CHANGED = "COMPANY_PRIORITY_CHANGED"


class OpportunityIngested(EventPayload):
    schema_version: int = 1
    opportunity_id: uuid.UUID
    artifact_id: uuid.UUID
    has_source_url: bool


class OpportunityExtracted(EventPayload):
    schema_version: int = 1
    opportunity_id: uuid.UUID
    llm_run_id: uuid.UUID
    company_id: uuid.UUID | None
    company_created: bool
    filled_fields: list[str]
    qualification_count: int
    dropped_qualification_count: int


class OpportunityContentEdited(EventPayload):
    schema_version: int = 1
    opportunity_id: uuid.UUID
    fields: list[str]


class OpportunityPriorityChanged(EventPayload):
    schema_version: int = 1
    opportunity_id: uuid.UUID
    from_priority: str
    to_priority: str


class CompanyCreated(EventPayload):
    schema_version: int = 1
    company_id: uuid.UUID
    origin: str


class CompanyPriorityChanged(EventPayload):
    schema_version: int = 1
    company_id: uuid.UUID
    from_priority: str
    to_priority: str


for event_type, model in (
    (OPPORTUNITY_INGESTED, OpportunityIngested),
    (OPPORTUNITY_EXTRACTED, OpportunityExtracted),
    (OPPORTUNITY_CONTENT_EDITED, OpportunityContentEdited),
    (OPPORTUNITY_PRIORITY_CHANGED, OpportunityPriorityChanged),
    (COMPANY_CREATED, CompanyCreated),
    (COMPANY_PRIORITY_CHANGED, CompanyPriorityChanged),
):
    payload_registry.register(event_type, model, version=1)


def record_event(
    session: Session,
    *,
    user_id: uuid.UUID,
    aggregate_type: AggregateType,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: EventPayload,
    actor: Actor,
) -> None:
    DomainEventRepository(session).append(
        user_id=user_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        actor=actor,
        payload=payload,
    )
