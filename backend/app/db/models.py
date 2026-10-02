import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
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


metadata = Base.metadata
