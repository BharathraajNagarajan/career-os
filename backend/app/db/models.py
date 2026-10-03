import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    HasCreatedAt,
    HasId,
    StateVersioned,
    TextEnum,
    UserOwned,
    enum_check,
    owned_fk,
    owned_table_args,
)


class UserStatus(StrEnum):
    ACTIVE = "active"
    DELETION_REQUESTED = "deletion_requested"


class AuthProvider(StrEnum):
    GOOGLE = "google"


class AggregateType(StrEnum):
    OPPORTUNITY = "opportunity"
    APPLICATION = "application"
    RECRUITING_ACTION = "recruiting_action"
    SKILL = "skill"
    CLAIM = "claim"
    CONTACT = "contact"
    COMPANY = "company"


class Actor(StrEnum):
    USER = "user"
    SYSTEM = "system"
    GMAIL = "gmail"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class RelocationPreference(StrEnum):
    OPEN = "open"
    NOT_OPEN = "not_open"
    UNSPECIFIED = "unspecified"


class RemotePreference(StrEnum):
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    NO_PREFERENCE = "no_preference"


class ArtifactKind(StrEnum):
    RESUME_FILE = "resume_file"
    JD_SNAPSHOT = "jd_snapshot"
    EMAIL_EXCERPT = "email_excerpt"
    REFERENCE = "reference"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResumeStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class LaneStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class LlmPurpose(StrEnum):
    EXTRACT_RESUME = "extract_resume"
    EXTRACT_JD = "extract_jd"
    CLASSIFY_EMAIL = "classify_email"
    EVALUATE = "evaluate"
    CHAT = "chat"
    PROPOSE_SKILL_EVIDENCE = "propose_skill_evidence"
    OUTREACH_RECOMMENDATION = "outreach_recommendation"
    OUTREACH_DRAFT = "outreach_draft"


class LlmTier(StrEnum):
    FAST = "fast"
    REASONING = "reasoning"


class LlmProviderName(StrEnum):
    FAKE = "fake"
    ANTHROPIC = "anthropic"


class LlmRunStatus(StrEnum):
    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReviewSource(StrEnum):
    GMAIL = "gmail"
    EXTRACTION = "extraction"
    CHAT = "chat"


class ProposalType(StrEnum):
    CLAIM = "claim"
    SKILL = "skill"
    SKILL_EVIDENCE = "skill_evidence"
    CREATE_APPLICATION = "create_application"
    APPLICATION_EVENT = "application_event"
    INTERACTION = "interaction"
    CONTACT_LINK = "contact_link"
    CONTACT_EMAIL = "contact_email"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class CompanyOrigin(StrEnum):
    USER = "user"
    EXTRACTED = "extracted"


class Priority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class OpportunityStatus(StrEnum):
    NEW = "new"
    SAVED = "saved"
    SKIPPED = "skipped"
    APPLIED = "applied"
    CLOSED = "closed"


class WorkplaceType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNSPECIFIED = "unspecified"


class OpportunitySource(StrEnum):
    MANUAL_PASTE = "manual_paste"


class QualificationKind(StrEnum):
    MINIMUM = "minimum"
    PREFERRED = "preferred"


class QualificationCategory(StrEnum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    DOMAIN = "domain"
    AUTHORIZATION = "authorization"
    LOCATION = "location"
    OTHER = "other"


class QualificationOrigin(StrEnum):
    EXTRACTED = "extracted"
    USER = "user"


class User(HasId, HasCreatedAt, Base):
    __tablename__ = "users"
    __table_args__ = (
        enum_check("status", UserStatus),
        Index("uq_users_primary_email_lower", func.lower(text("primary_email")), unique=True),
    )

    primary_email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[UserStatus] = mapped_column(
        TextEnum(UserStatus), server_default=UserStatus.ACTIVE.value
    )
    deleted_at: Mapped[datetime | None]


class AuthIdentity(UserOwned, HasCreatedAt, Base):
    __tablename__ = "auth_identities"
    __table_args__ = owned_table_args(
        enum_check("provider", AuthProvider),
        UniqueConstraint("provider", "provider_subject"),
    )

    provider: Mapped[AuthProvider] = mapped_column(TextEnum(AuthProvider))
    provider_subject: Mapped[str] = mapped_column(Text)
    email_at_login: Mapped[str] = mapped_column(Text)
    last_login_at: Mapped[datetime]


class UserSession(UserOwned, HasCreatedAt, Base):
    __tablename__ = "sessions"
    __table_args__ = owned_table_args()

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    user_agent_hash: Mapped[str | None] = mapped_column(Text)


class DomainEvent(UserOwned, Base):
    __tablename__ = "domain_events"
    __table_args__ = owned_table_args(
        enum_check("aggregate_type", AggregateType),
        enum_check("actor", Actor),
        owned_fk("voids_event_id", "domain_events"),
        Index(
            "ix_domain_events_aggregate", "user_id", "aggregate_type", "aggregate_id", "occurred_at"
        ),
    )

    aggregate_type: Mapped[AggregateType] = mapped_column(TextEnum(AggregateType))
    aggregate_id: Mapped[uuid.UUID]
    event_type: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime]
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor: Mapped[Actor] = mapped_column(TextEnum(Actor))
    source_ref_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    voids_event_id: Mapped[uuid.UUID | None]
    correlation_id: Mapped[uuid.UUID | None]


class Job(HasId, HasCreatedAt, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("status", JobStatus),
        Index(
            "uq_jobs_unique_key_active",
            "unique_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(
        TextEnum(JobStatus), server_default=JobStatus.QUEUED.value
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="5")
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None]
    unique_key: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[uuid.UUID | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None]


class Profile(UserOwned, Base):
    __tablename__ = "profiles"
    __table_args__ = owned_table_args(
        enum_check("relocation_preference", RelocationPreference),
        enum_check("remote_preference", RemotePreference),
        UniqueConstraint("user_id"),
    )

    headline: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(Text)
    relocation_preference: Mapped[RelocationPreference] = mapped_column(
        TextEnum(RelocationPreference), server_default=RelocationPreference.UNSPECIFIED.value
    )
    remote_preference: Mapped[RemotePreference] = mapped_column(
        TextEnum(RemotePreference), server_default=RemotePreference.NO_PREFERENCE.value
    )
    work_authorization: Mapped[dict[str, Any]] = mapped_column(JSONB)
    constraints_updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    target_roles: Mapped[dict[str, Any]] = mapped_column(JSONB)
    communication_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Artifact(UserOwned, HasCreatedAt, Base):
    __tablename__ = "artifacts"
    __table_args__ = owned_table_args(
        enum_check("kind", ArtifactKind),
        enum_check("extraction_status", ExtractionStatus),
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        UniqueConstraint("user_id", "sha256", "kind"),
    )

    kind: Mapped[ArtifactKind] = mapped_column(TextEnum(ArtifactKind))
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[bytes] = mapped_column(LargeBinary)
    mime_type: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int]
    original_filename: Mapped[str] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        TextEnum(ExtractionStatus), server_default=ExtractionStatus.PENDING.value
    )
    extraction_error_code: Mapped[str | None] = mapped_column(Text)


class Resume(UserOwned, HasCreatedAt, Base):
    __tablename__ = "resumes"
    __table_args__ = owned_table_args(
        enum_check("status", ResumeStatus),
        owned_fk("artifact_id", "artifacts"),
        owned_fk("lane_id", "resume_lanes"),
        UniqueConstraint("artifact_id"),
    )

    artifact_id: Mapped[uuid.UUID]
    label: Mapped[str] = mapped_column(Text)
    lane_id: Mapped[uuid.UUID | None]
    parsed_outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[ResumeStatus] = mapped_column(
        TextEnum(ResumeStatus), server_default=ResumeStatus.ACTIVE.value
    )
    archived_at: Mapped[datetime | None]


class ResumeLane(UserOwned, HasCreatedAt, Base):
    __tablename__ = "resume_lanes"
    __table_args__ = owned_table_args(
        enum_check("status", LaneStatus),
        owned_fk("default_resume_id", "resumes", use_alter=True),
        Index(
            "uq_resume_lanes_active_name",
            "user_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    emphasis_notes: Mapped[str] = mapped_column(Text, server_default="")
    target_role_labels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    default_resume_id: Mapped[uuid.UUID | None]
    status: Mapped[LaneStatus] = mapped_column(
        TextEnum(LaneStatus), server_default=LaneStatus.ACTIVE.value
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class LlmRun(UserOwned, Base):
    __tablename__ = "llm_runs"
    __table_args__ = owned_table_args(
        enum_check("purpose", LlmPurpose),
        enum_check("tier", LlmTier),
        enum_check("provider", LlmProviderName),
        enum_check("status", LlmRunStatus),
        owned_fk("repair_of_run_id", "llm_runs"),
        CheckConstraint("attempt IN (1, 2)", name="attempt"),
        CheckConstraint("(attempt = 1) = (repair_of_run_id IS NULL)", name="repair_link"),
        CheckConstraint("max_output_tokens > 0", name="max_output_tokens_positive"),
        CheckConstraint("reserved_cost_usd >= 0", name="reserved_cost_nonnegative"),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="cost_nonnegative"),
        CheckConstraint(
            "(status = 'reserved') = (cost_usd IS NULL) AND "
            "(status = 'reserved') = (settled_at IS NULL)",
            name="settlement_consistent",
        ),
        CheckConstraint("jsonb_typeof(context_manifest) = 'object'", name="manifest_object"),
        Index("ix_llm_runs_user_id_created_at", "user_id", "created_at"),
    )

    purpose: Mapped[LlmPurpose] = mapped_column(TextEnum(LlmPurpose))
    prompt_id: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[int]
    provider: Mapped[LlmProviderName] = mapped_column(TextEnum(LlmProviderName))
    model: Mapped[str] = mapped_column(Text)
    tier: Mapped[LlmTier] = mapped_column(TextEnum(LlmTier))
    max_output_tokens: Mapped[int]
    attempt: Mapped[int] = mapped_column(server_default="1")
    repair_of_run_id: Mapped[uuid.UUID | None]
    status: Mapped[LlmRunStatus] = mapped_column(TextEnum(LlmRunStatus))
    error_code: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]
    reserved_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    context_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime]
    settled_at: Mapped[datetime | None]


class ReviewItem(UserOwned, StateVersioned, HasCreatedAt, Base):
    __tablename__ = "review_items"
    __table_args__ = owned_table_args(
        enum_check("source", ReviewSource),
        enum_check("proposal_type", ProposalType),
        enum_check("status", ReviewStatus),
        owned_fk("llm_run_id", "llm_runs"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        CheckConstraint(
            "jsonb_typeof(proposed_payload) = 'object'", name="proposed_payload_object"
        ),
        CheckConstraint(
            "decided_payload IS NULL OR jsonb_typeof(decided_payload) = 'object'",
            name="decided_payload_object",
        ),
        CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="decision_consistent"),
        CheckConstraint(
            "decided_payload IS NULL OR status = 'confirmed'", name="decided_payload_confirmed"
        ),
        Index("ix_review_items_user_id_status_created_at", "user_id", "status", "created_at"),
    )

    source: Mapped[ReviewSource] = mapped_column(TextEnum(ReviewSource))
    proposal_type: Mapped[ProposalType] = mapped_column(TextEnum(ProposalType))
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_ref_id: Mapped[uuid.UUID | None]
    status: Mapped[ReviewStatus] = mapped_column(
        TextEnum(ReviewStatus), server_default=ReviewStatus.PENDING.value
    )
    decided_at: Mapped[datetime | None]
    llm_run_id: Mapped[uuid.UUID | None]
    decided_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Company(UserOwned, HasCreatedAt, Base):
    __tablename__ = "companies"
    __table_args__ = owned_table_args(
        enum_check("strategic_priority", Priority),
        enum_check("origin", CompanyOrigin),
        UniqueConstraint("user_id", "normalized_name"),
        CheckConstraint("normalized_name <> ''", name="normalized_name_not_empty"),
    )

    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    careers_url: Mapped[str | None] = mapped_column(Text)
    strategic_priority: Mapped[Priority] = mapped_column(
        TextEnum(Priority), server_default=Priority.NORMAL.value
    )
    notes: Mapped[str] = mapped_column(Text, server_default="")
    origin: Mapped[CompanyOrigin] = mapped_column(TextEnum(CompanyOrigin))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Opportunity(UserOwned, StateVersioned, HasCreatedAt, Base):
    __tablename__ = "opportunities"
    __table_args__ = owned_table_args(
        enum_check("status", OpportunityStatus),
        enum_check("priority", Priority),
        enum_check("extraction_status", ExtractionStatus),
        enum_check("workplace_type", WorkplaceType),
        enum_check("source", OpportunitySource),
        owned_fk("company_id", "companies"),
        owned_fk("jd_artifact_id", "artifacts"),
        owned_fk("llm_run_id", "llm_runs"),
        UniqueConstraint("jd_artifact_id"),
        CheckConstraint(
            "(extraction_status = 'failed') = (extraction_error_code IS NOT NULL)",
            name="extraction_error_consistent",
        ),
        CheckConstraint("jsonb_typeof(locations) = 'object'", name="locations_object"),
        Index(
            "uq_opportunities_company_external_job_id",
            "user_id",
            "company_id",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL AND company_id IS NOT NULL"),
        ),
        Index("ix_opportunities_user_id_discovered_at", "user_id", "discovered_at"),
        Index("ix_opportunities_user_id_company_id", "user_id", "company_id"),
    )

    company_id: Mapped[uuid.UUID | None]
    title: Mapped[str | None] = mapped_column(Text)
    team: Mapped[str | None] = mapped_column(Text)
    external_job_id: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(Text)
    locations: Mapped[dict[str, Any]] = mapped_column(JSONB)
    workplace_type: Mapped[WorkplaceType] = mapped_column(
        TextEnum(WorkplaceType), server_default=WorkplaceType.UNSPECIFIED.value
    )
    source: Mapped[OpportunitySource] = mapped_column(TextEnum(OpportunitySource))
    source_url: Mapped[str | None] = mapped_column(Text)
    jd_artifact_id: Mapped[uuid.UUID]
    status: Mapped[OpportunityStatus] = mapped_column(
        TextEnum(OpportunityStatus), server_default=OpportunityStatus.NEW.value
    )
    priority: Mapped[Priority] = mapped_column(
        TextEnum(Priority), server_default=Priority.NORMAL.value
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        TextEnum(ExtractionStatus), server_default=ExtractionStatus.PENDING.value
    )
    extraction_error_code: Mapped[str | None] = mapped_column(Text)
    llm_run_id: Mapped[uuid.UUID | None]
    latest_evaluation_id: Mapped[uuid.UUID | None]
    content_updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    discovered_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Qualification(UserOwned, HasCreatedAt, Base):
    __tablename__ = "qualifications"
    __table_args__ = owned_table_args(
        enum_check("kind", QualificationKind),
        enum_check("category", QualificationCategory),
        enum_check("origin", QualificationOrigin),
        owned_fk("opportunity_id", "opportunities"),
        owned_fk("llm_run_id", "llm_runs"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "char_length(text_verbatim) BETWEEN 1 AND 2000", name="text_verbatim_length"
        ),
        CheckConstraint("min_years IS NULL OR min_years BETWEEN 0 AND 50", name="min_years_range"),
        Index("ix_qualifications_user_id_opportunity_id", "user_id", "opportunity_id"),
    )

    opportunity_id: Mapped[uuid.UUID]
    kind: Mapped[QualificationKind] = mapped_column(TextEnum(QualificationKind))
    ordinal: Mapped[int]
    text_verbatim: Mapped[str] = mapped_column(Text)
    category: Mapped[QualificationCategory] = mapped_column(TextEnum(QualificationCategory))
    skill_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    min_years: Mapped[int | None]
    is_hard_constraint: Mapped[bool] = mapped_column(server_default=text("false"))
    origin: Mapped[QualificationOrigin] = mapped_column(TextEnum(QualificationOrigin))
    llm_run_id: Mapped[uuid.UUID | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


metadata = Base.metadata
