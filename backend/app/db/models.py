import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, LargeBinary, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
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


metadata = Base.metadata
