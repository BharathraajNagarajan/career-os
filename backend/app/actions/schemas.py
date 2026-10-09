import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.actions.commands import allowed_user_commands
from app.db.models import (
    ActionOrigin,
    RecruitingAction,
    RecruitingActionKind,
    RecruitingActionStatus,
)
from app.opportunities.normalize import collapse_whitespace
from app.state_machines.recruiting_action import RecruitingActionCommand

TITLE_MAX_CHARS = 200


def clean_title(value: str) -> str:
    cleaned = collapse_whitespace(value)
    if not cleaned:
        raise ValueError("title is required")
    return cleaned


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionCreate(StrictModel):
    kind: RecruitingActionKind
    title: str = Field(max_length=TITLE_MAX_CHARS)
    due_at: AwareDatetime | None = None
    opportunity_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    interaction_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        return clean_title(value)


class ActionPatch(StrictModel):
    expected_state_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=TITLE_MAX_CHARS)
    due_at: AwareDatetime | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)


class ActionVersion(StrictModel):
    expected_state_version: int = Field(ge=1)


class ActionSnooze(StrictModel):
    expected_state_version: int = Field(ge=1)
    until: AwareDatetime


class ActionResponse(BaseModel):
    id: uuid.UUID
    kind: RecruitingActionKind
    title: str
    due_at: datetime | None
    status: RecruitingActionStatus
    snoozed_until: datetime | None
    sequence_no: int
    opportunity_id: uuid.UUID | None
    application_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    interaction_id: uuid.UUID | None
    origin: ActionOrigin
    state_version: int
    allowed_actions: list[RecruitingActionCommand]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: RecruitingAction) -> Self:
        return cls(
            id=row.id,
            kind=row.kind,
            title=row.title,
            due_at=row.due_at,
            status=row.status,
            snoozed_until=row.snoozed_until,
            sequence_no=row.sequence_no,
            opportunity_id=row.opportunity_id,
            application_id=row.application_id,
            contact_id=row.contact_id,
            interaction_id=row.interaction_id,
            origin=row.origin,
            state_version=row.state_version,
            allowed_actions=allowed_user_commands(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
