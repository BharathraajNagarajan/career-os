import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.db.models import Interaction, InteractionChannel, InteractionDirection
from app.opportunities.normalize import clean_note
from app.state_machines.application import ApplicationEventType

SUMMARY_MAX_CHARS = 2000


class InteractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: uuid.UUID
    channel: InteractionChannel
    direction: InteractionDirection
    occurred_at: AwareDatetime
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_CHARS)
    opportunity_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    application_event_type: ApplicationEventType | None = None
    expected_application_state_version: int | None = Field(default=None, ge=1)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str | None) -> str | None:
        return clean_note(value)


class InteractionResponse(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    company_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    application_id: uuid.UUID | None
    channel: InteractionChannel
    direction: InteractionDirection
    occurred_at: datetime
    summary: str | None
    created_at: datetime
    application_state_version: int | None = None

    @classmethod
    def build(cls, row: Interaction, *, application_state_version: int | None = None) -> Self:
        return cls(
            id=row.id,
            contact_id=row.contact_id,
            company_id=row.company_id,
            opportunity_id=row.opportunity_id,
            application_id=row.application_id,
            channel=row.channel,
            direction=row.direction,
            occurred_at=row.occurred_at,
            summary=row.summary,
            created_at=row.created_at,
            application_state_version=application_state_version,
        )
