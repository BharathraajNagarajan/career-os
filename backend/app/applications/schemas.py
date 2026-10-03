import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.applications.events import NOTE_MAX_CHARS, REASON_MAX_CHARS
from app.db.models import (
    Actor,
    AggregateType,
    Application,
    ApplicationChannel,
    ApplicationStage,
    Company,
    Opportunity,
)
from app.opportunities.normalize import clean_note, collapse_whitespace
from app.opportunities.schemas import OpportunityDetail
from app.state_machines.application import ApplicationEventType, recordable_event_types


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordEventRequest(StrictModel):
    expected_state_version: int = Field(ge=1)
    event_type: ApplicationEventType
    occurred_at: AwareDatetime
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        return clean_note(value)


class VoidEventRequest(StrictModel):
    expected_state_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=REASON_MAX_CHARS)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str | None) -> str | None:
        return clean_note(value)


class ReopenRequest(StrictModel):
    expected_state_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        return clean_note(value)


class ApplicationResponse(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    opportunity_title: str | None
    company_name: str | None
    resume_id: uuid.UUID | None
    lane_id: uuid.UUID | None
    applied_at: datetime
    channel: ApplicationChannel
    stage: ApplicationStage
    is_terminal: bool
    state_version: int
    recordable_event_types: list[ApplicationEventType]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: Application, opportunity: Opportunity, company: Company | None) -> Self:
        return cls(
            id=row.id,
            opportunity_id=row.opportunity_id,
            opportunity_title=opportunity.title,
            company_name=None if company is None else collapse_whitespace(company.name),
            resume_id=row.resume_id,
            lane_id=row.lane_id,
            applied_at=row.applied_at,
            channel=row.channel,
            stage=row.stage,
            is_terminal=row.is_terminal,
            state_version=row.state_version,
            recordable_event_types=recordable_event_types(row.is_terminal),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ApplyResponse(BaseModel):
    opportunity: OpportunityDetail
    application: ApplicationResponse


class TimelineEntryResponse(BaseModel):
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
