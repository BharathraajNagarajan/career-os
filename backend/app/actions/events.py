import uuid
from datetime import datetime

from pydantic import Field

from app.events.payloads import EventPayload, payload_registry
from app.state_machines.recruiting_action import RecruitingActionCommand

ACTION_CREATED = "RECRUITING_ACTION_CREATED"
ACTION_EDITED = "RECRUITING_ACTION_EDITED"

TRANSITION_EVENTS: dict[RecruitingActionCommand, str] = {
    RecruitingActionCommand.SNOOZE: "RECRUITING_ACTION_SNOOZED",
    RecruitingActionCommand.WAKE: "RECRUITING_ACTION_WOKEN",
    RecruitingActionCommand.COMPLETE: "RECRUITING_ACTION_COMPLETED",
    RecruitingActionCommand.DISMISS: "RECRUITING_ACTION_DISMISSED",
    RecruitingActionCommand.SUPERSEDE: "RECRUITING_ACTION_SUPERSEDED",
    RecruitingActionCommand.RESTORE: "RECRUITING_ACTION_RESTORED",
}


class RecruitingActionCreated(EventPayload):
    schema_version: int = 1
    action_id: uuid.UUID
    kind: str
    origin: str
    due_at: datetime | None
    opportunity_id: uuid.UUID | None
    application_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    interaction_id: uuid.UUID | None


class RecruitingActionEdited(EventPayload):
    schema_version: int = 1
    action_id: uuid.UUID
    fields: list[str] = Field(max_length=5)


class RecruitingActionTransitioned(EventPayload):
    schema_version: int = 1
    action_id: uuid.UUID
    from_status: str
    to_status: str
    snoozed_until: datetime | None


payload_registry.register(ACTION_CREATED, RecruitingActionCreated, version=1)
payload_registry.register(ACTION_EDITED, RecruitingActionEdited, version=1)
for event_type in TRANSITION_EVENTS.values():
    payload_registry.register(event_type, RecruitingActionTransitioned, version=1)
