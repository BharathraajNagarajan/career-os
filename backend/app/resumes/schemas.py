import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.artifacts.outline import ParsedOutline
from app.db.models import Artifact, ExtractionStatus, LaneStatus, Resume, ResumeLane, ResumeStatus

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LaneName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
RoleLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumeSummary(BaseModel):
    id: uuid.UUID
    label: str
    status: ResumeStatus
    archived: bool
    lane_id: uuid.UUID | None
    original_filename: str
    mime_type: str
    byte_size: int
    extraction_status: ExtractionStatus
    extraction_error_code: str | None
    created_at: datetime
    archived_at: datetime | None

    @classmethod
    def build(cls, resume: Resume, artifact: Artifact) -> "ResumeSummary":
        return cls(
            id=resume.id,
            label=resume.label,
            status=resume.status,
            archived=resume.status is ResumeStatus.ARCHIVED,
            lane_id=resume.lane_id,
            original_filename=artifact.original_filename,
            mime_type=artifact.mime_type,
            byte_size=artifact.byte_size,
            extraction_status=artifact.extraction_status,
            extraction_error_code=artifact.extraction_error_code,
            created_at=resume.created_at,
            archived_at=resume.archived_at,
        )


class ResumeDetail(ResumeSummary):
    parsed_outline: ParsedOutline | None

    @classmethod
    def build_detail(cls, resume: Resume, artifact: Artifact) -> "ResumeDetail":
        outline = None if resume.parsed_outline is None else resume.parsed_outline
        return cls(
            **ResumeSummary.build(resume, artifact).model_dump(),
            parsed_outline=None if outline is None else ParsedOutline.model_validate(outline),
        )


class ResumePatch(StrictModel):
    label: Label | None = None
    lane_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def label_is_not_nulled(self) -> "ResumePatch":
        if "label" in self.model_fields_set and self.label is None:
            raise ValueError("label cannot be null")
        return self


class LaneCreate(StrictModel):
    name: LaneName
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    emphasis_notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    target_role_labels: list[RoleLabel] = Field(default_factory=list, max_length=20)


class LanePatch(StrictModel):
    name: LaneName | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
    ) = None
    emphasis_notes: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None
    target_role_labels: list[RoleLabel] | None = Field(default=None, max_length=20)
    default_resume_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def required_fields_are_not_nulled(self) -> "LanePatch":
        for field in ("name", "description", "emphasis_notes", "target_role_labels"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LaneResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    emphasis_notes: str
    target_role_labels: list[str]
    default_resume_id: uuid.UUID | None
    status: LaneStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, lane: ResumeLane) -> "LaneResponse":
        return cls(
            id=lane.id,
            name=lane.name,
            description=lane.description,
            emphasis_notes=lane.emphasis_notes,
            target_role_labels=list(lane.target_role_labels),
            default_resume_id=lane.default_resume_id,
            status=lane.status,
            created_at=lane.created_at,
            updated_at=lane.updated_at,
        )
