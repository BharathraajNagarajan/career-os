import uuid
from datetime import date
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.models import EngagementType, EvidenceClass

SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ClaimProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    evidence_class: EvidenceClass
    engagement_type: EngagementType | None
    start_date: date | None = None
    end_date: date | None = None
    organization_label: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    skill_names: list[SkillName] = Field(default_factory=list, max_length=20)
    resume_id: uuid.UUID
    confirm_class_change: bool = False

    @model_validator(mode="after")
    def engagement_type_matches_class(self) -> Self:
        if (self.evidence_class is EvidenceClass.PROFESSIONAL) != (
            self.engagement_type is not None
        ):
            raise ValueError("engagement_type is required for professional claims only")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date before start_date")
        return self


class SkillProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: SkillName
    resume_id: uuid.UUID
