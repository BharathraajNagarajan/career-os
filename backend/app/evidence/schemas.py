import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.models import (
    ConfirmationStatus,
    EngagementType,
    EvidenceClass,
    EvidenceOrigin,
    EvidenceSourceType,
)
from app.evidence.assessment import Category, HeadlineCategory

SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Statement = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Organization = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Version = Annotated[int, Field(ge=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillCreate(StrictModel):
    canonical_name: SkillName
    aliases: list[SkillName] = Field(default_factory=list, max_length=30)
    user_note: Note = ""


class SkillPatch(StrictModel):
    expected_state_version: Version
    canonical_name: SkillName | None = None
    aliases: list[SkillName] | None = Field(default=None, max_length=30)
    user_note: Note | None = None

    @model_validator(mode="after")
    def required_fields_are_not_nulled(self) -> "SkillPatch":
        for name in ("canonical_name", "aliases", "user_note"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class SkillMergeRequest(StrictModel):
    merged_id: uuid.UUID
    expected_state_version: Version
    expected_merged_state_version: Version


class MarkGapRequest(StrictModel):
    expected_state_version: Version
    note: Note | None = None


class ClearGapRequest(StrictModel):
    expected_state_version: Version


class SourceCreate(StrictModel):
    source_type: EvidenceSourceType
    resume_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    assertion_text: Note | None = None
    locator: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ClaimCreate(StrictModel):
    statement: Statement
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None = None
    start_date: date | None = None
    end_date: date | None = None
    organization_label: Organization | None = None
    skill_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    sources: list[SourceCreate] = Field(min_length=1, max_length=10)


class ClaimPatch(StrictModel):
    expected_state_version: Version
    statement: Statement | None = None
    start_date: date | None = None
    end_date: date | None = None
    organization_label: Organization | None = None

    @model_validator(mode="after")
    def statement_is_not_nulled(self) -> "ClaimPatch":
        if "statement" in self.model_fields_set and self.statement is None:
            raise ValueError("statement cannot be null")
        return self


class ClassificationRequest(StrictModel):
    expected_state_version: Version
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None = None
    confirm_change: bool


class RejectClaimRequest(StrictModel):
    expected_state_version: Version


class LinkSkillRequest(StrictModel):
    skill_id: uuid.UUID


class BadgeResponse(BaseModel):
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    confirmed: bool
    claim_count: int


class HeadlineResponse(BaseModel):
    category: HeadlineCategory
    engagement_type: EngagementType | None


class ResumeExposure(BaseModel):
    resume_id: uuid.UUID
    label: str
    archived: bool
    stated: bool
    mentioned: bool


class SourceResponse(BaseModel):
    id: uuid.UUID
    source_type: EvidenceSourceType
    resume_id: uuid.UUID | None
    resume_label: str | None
    artifact_id: uuid.UUID | None
    url: str | None
    assertion_text: str | None
    locator: str | None
    created_at: datetime


class SkillRef(BaseModel):
    id: uuid.UUID
    canonical_name: str


class ClaimResponse(BaseModel):
    id: uuid.UUID
    statement: str
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    confirmation_status: ConfirmationStatus
    start_date: date | None
    end_date: date | None
    organization_label: str | None
    origin: EvidenceOrigin
    skills: list[SkillRef]
    sources: list[SourceResponse]
    state_version: int
    created_at: datetime
    updated_at: datetime


class SkillSummary(BaseModel):
    id: uuid.UUID
    canonical_name: str
    aliases: list[str]
    confirmation_status: ConfirmationStatus
    user_marked_gap: bool
    headline: HeadlineResponse
    categories: list[Category]
    badges: list[BadgeResponse]
    latest_end_date: date | None
    is_current: bool
    exposure: list[ResumeExposure]
    merged_into_skill_id: uuid.UUID | None
    state_version: int
    updated_at: datetime


class SkillDetail(SkillSummary):
    gap_note: str | None
    user_note: str
    origin: EvidenceOrigin
    claims: list[ClaimResponse]
    created_at: datetime


EngagementFilter = Literal["full_time", "part_time", "contract", "internship", "unspecified"]
