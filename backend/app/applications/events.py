import uuid
from typing import Any

from pydantic import Field

from app.events.payloads import EventPayload, payload_registry
from app.state_machines.application import ApplicationEventType

NOTE_MAX_CHARS = 1000
REASON_MAX_CHARS = 500

SUBMITTED = ApplicationEventType.APPLICATION_SUBMITTED
VOIDED = ApplicationEventType.EVENT_VOIDED


class ApplicationSubmitted(EventPayload):
    schema_version: int = 1
    application_id: uuid.UUID
    opportunity_id: uuid.UUID
    resume_id: uuid.UUID | None
    lane_id: uuid.UUID | None
    channel: str


class ApplicationNoted(EventPayload):
    schema_version: int = 2
    application_id: uuid.UUID
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)
    interaction_id: uuid.UUID | None = None


def noted_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    return {**data, "interaction_id": None}


class ApplicationEventVoided(EventPayload):
    schema_version: int = 1
    application_id: uuid.UUID
    voided_event_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=REASON_MAX_CHARS)


payload_registry.register(SUBMITTED.value, ApplicationSubmitted, version=1)
payload_registry.register(VOIDED.value, ApplicationEventVoided, version=1)
for event_type in ApplicationEventType:
    if event_type not in {SUBMITTED, VOIDED}:
        payload_registry.register(
            event_type.value, ApplicationNoted, version=2, upcasters={1: noted_v1_to_v2}
        )
