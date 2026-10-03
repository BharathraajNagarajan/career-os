import uuid
from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import (
    Company,
    CompanyOrigin,
    ExtractionStatus,
    Opportunity,
    OpportunityStatus,
    Priority,
    Qualification,
    QualificationCategory,
    QualificationKind,
    QualificationOrigin,
    WorkplaceType,
)
from app.opportunities.countries import ISO_3166_ALPHA2
from app.opportunities.normalize import collapse_whitespace, normalize_domain, normalize_skill_keys

MAX_URL_CHARS = 2048
MAX_LOCATION_ITEMS = 10
MAX_ALIASES = 20
MAX_DOMAINS = 20
MAX_REQUEST_JD_CHARS = 400_000

Reason = Literal["exact_job_id", "similar_title"]


def clean_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    parts = urlsplit(cleaned)
    if (
        len(cleaned) > MAX_URL_CHARS
        or parts.scheme.lower() not in {"http", "https"}
        or not parts.hostname
        or any(char.isspace() or ord(char) < 32 for char in cleaned)
    ):
        raise ValueError("must be an http or https URL")
    return cleaned


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = collapse_whitespace(value)
    return cleaned or None


def clean_name(value: str) -> str:
    cleaned = collapse_whitespace(value)
    if not cleaned:
        raise ValueError("name is required")
    return cleaned


def clean_aliases(value: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for alias in value:
        cleaned = collapse_whitespace(alias)
        if len(cleaned) > 200:
            raise ValueError("alias is too long")
        if cleaned:
            seen.setdefault(cleaned.lower(), cleaned)
    return list(seen.values())


def clean_domains(value: list[str]) -> list[str]:
    cleaned: dict[str, None] = {}
    for raw in value:
        domain = normalize_domain(raw)
        if domain is None:
            raise ValueError("domain is not a valid hostname")
        cleaned.setdefault(domain)
    return list(cleaned)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationItem(StrictModel):
    city: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    country: str | None = None

    @field_validator("city", "region")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        return clean_optional_text(value)

    @field_validator("country")
    @classmethod
    def _clean_country(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        code = value.strip().upper()
        if code not in ISO_3166_ALPHA2:
            raise ValueError("country must be an ISO 3166-1 alpha-2 code")
        return code


class Locations(StrictModel):
    schema_version: Literal[1] = 1
    items: list[LocationItem] = Field(default_factory=list, max_length=MAX_LOCATION_ITEMS)


class IngestRequest(StrictModel):
    jd_text: str = Field(max_length=MAX_REQUEST_JD_CHARS)
    source_url: str | None = None

    @field_validator("source_url")
    @classmethod
    def _clean_source_url(cls, value: str | None) -> str | None:
        return clean_url(value)


class OpportunityPatch(StrictModel):
    expected_state_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=300)
    team: str | None = Field(default=None, max_length=300)
    external_job_id: str | None = Field(default=None, max_length=200)
    location_text: str | None = Field(default=None, max_length=500)
    locations: Locations | None = None
    workplace_type: WorkplaceType | None = None
    company_id: uuid.UUID | None = None
    source_url: str | None = None

    @field_validator("title", "team", "external_job_id", "location_text")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        return clean_optional_text(value)

    @field_validator("source_url")
    @classmethod
    def _clean_source_url(cls, value: str | None) -> str | None:
        return clean_url(value)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> Self:
        for name in ("locations", "workplace_type"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PriorityRequest(StrictModel):
    priority: Priority


def clean_skill_keys(value: list[str]) -> list[str]:
    return normalize_skill_keys(value)


class QualificationCreate(StrictModel):
    kind: QualificationKind
    text_verbatim: str = Field(max_length=4000)
    category: QualificationCategory
    skill_keys: list[str] = Field(default_factory=list, max_length=50)
    min_years: int | None = Field(default=None, ge=0, le=50)
    is_hard_constraint: bool = False
    ordinal: int | None = Field(default=None, ge=0)

    @field_validator("text_verbatim")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        cleaned = collapse_whitespace(value)
        if not cleaned or len(cleaned) > 1000:
            raise ValueError("text must be 1 to 1000 characters")
        return cleaned

    @field_validator("skill_keys")
    @classmethod
    def _clean_keys(cls, value: list[str]) -> list[str]:
        return clean_skill_keys(value)


class QualificationPatch(StrictModel):
    kind: QualificationKind | None = None
    category: QualificationCategory | None = None
    skill_keys: list[str] | None = Field(default=None, max_length=50)
    min_years: int | None = Field(default=None, ge=0, le=50)
    is_hard_constraint: bool | None = None
    ordinal: int | None = Field(default=None, ge=0)

    @field_validator("skill_keys")
    @classmethod
    def _clean_keys(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_skill_keys(value)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> Self:
        for name in ("kind", "category", "skill_keys", "is_hard_constraint", "ordinal"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class QualificationResponse(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    kind: QualificationKind
    ordinal: int
    text_verbatim: str
    category: QualificationCategory
    skill_keys: list[str]
    min_years: int | None
    is_hard_constraint: bool
    origin: QualificationOrigin
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: Qualification) -> Self:
        return cls.model_validate(row, from_attributes=True)


class CompanyRef(BaseModel):
    id: uuid.UUID
    name: str
    strategic_priority: Priority

    @classmethod
    def build(cls, row: Company | None) -> Self | None:
        return None if row is None else cls.model_validate(row, from_attributes=True)


class OpportunitySummary(BaseModel):
    id: uuid.UUID
    company: CompanyRef | None
    title: str | None
    status: OpportunityStatus
    priority: Priority
    extraction_status: ExtractionStatus
    extraction_error_code: str | None
    workplace_type: WorkplaceType
    location_text: str | None
    source_url: str | None
    content_updated_at: datetime
    discovered_at: datetime
    state_version: int

    @classmethod
    def build(cls, row: Opportunity, company: Company | None) -> Self:
        return cls(
            id=row.id,
            company=CompanyRef.build(company),
            title=row.title,
            status=row.status,
            priority=row.priority,
            extraction_status=row.extraction_status,
            extraction_error_code=row.extraction_error_code,
            workplace_type=row.workplace_type,
            location_text=row.location_text,
            source_url=row.source_url,
            content_updated_at=row.content_updated_at,
            discovered_at=row.discovered_at,
            state_version=row.state_version,
        )


class OpportunityDetail(OpportunitySummary):
    team: str | None
    external_job_id: str | None
    locations: Locations
    jd_artifact_id: uuid.UUID
    jd_text: str
    llm_run_id: uuid.UUID | None
    qualifications: list[QualificationResponse]

    @classmethod
    def build_detail(
        cls,
        row: Opportunity,
        company: Company | None,
        jd_text: str,
        qualifications: list[Qualification],
    ) -> Self:
        summary = OpportunitySummary.build(row, company)
        return cls(
            **summary.model_dump(),
            team=row.team,
            external_job_id=row.external_job_id,
            locations=Locations.model_validate(row.locations),
            jd_artifact_id=row.jd_artifact_id,
            jd_text=jd_text,
            llm_run_id=row.llm_run_id,
            qualifications=[QualificationResponse.build(item) for item in qualifications],
        )


class DuplicateMatch(BaseModel):
    opportunity: OpportunitySummary
    reason: Reason
    similarity: float


class CompanyFields(StrictModel):
    aliases: list[str] = Field(default_factory=list, max_length=MAX_ALIASES)
    domains: list[str] = Field(default_factory=list, max_length=MAX_DOMAINS)
    careers_url: str | None = None
    notes: str = Field(default="", max_length=5000)
    strategic_priority: Priority = Priority.NORMAL

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, value: list[str]) -> list[str]:
        return clean_aliases(value)

    @field_validator("domains")
    @classmethod
    def _clean_domains(cls, value: list[str]) -> list[str]:
        return clean_domains(value)

    @field_validator("careers_url")
    @classmethod
    def _clean_careers_url(cls, value: str | None) -> str | None:
        return clean_url(value)


class CompanyCreate(CompanyFields):
    name: str = Field(max_length=200)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_name(value)


class CompanyPatch(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=MAX_ALIASES)
    domains: list[str] | None = Field(default=None, max_length=MAX_DOMAINS)
    careers_url: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    strategic_priority: Priority | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_aliases(value)

    @field_validator("domains")
    @classmethod
    def _clean_domains(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_domains(value)

    @field_validator("careers_url")
    @classmethod
    def _clean_careers_url(cls, value: str | None) -> str | None:
        return clean_url(value)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> Self:
        for name in ("name", "aliases", "domains", "notes", "strategic_priority"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    normalized_name: str
    aliases: list[str]
    domains: list[str]
    careers_url: str | None
    strategic_priority: Priority
    notes: str
    origin: CompanyOrigin
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, row: Company) -> Self:
        return cls.model_validate(row, from_attributes=True)


class CompanyDetail(CompanyResponse):
    opportunity_counts: dict[OpportunityStatus, int]

    @classmethod
    def build_detail(cls, row: Company, counts: dict[OpportunityStatus, int]) -> Self:
        return cls(**CompanyResponse.build(row).model_dump(), opportunity_counts=counts)
