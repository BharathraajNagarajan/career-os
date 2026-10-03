"""companies, opportunities, qualifications

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"
EMPTY_ARRAY = sa.text("'{}'::text[]")


def timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column(
            "aliases", postgresql.ARRAY(sa.Text()), server_default=EMPTY_ARRAY, nullable=False
        ),
        sa.Column(
            "domains", postgresql.ARRAY(sa.Text()), server_default=EMPTY_ARRAY, nullable=False
        ),
        sa.Column("careers_url", sa.Text(), nullable=True),
        sa.Column("strategic_priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "strategic_priority IN ('high', 'normal', 'low')",
            name=op.f("ck_companies_strategic_priority"),
        ),
        sa.CheckConstraint("origin IN ('user', 'extracted')", name=op.f("ck_companies_origin")),
        sa.CheckConstraint(
            "normalized_name <> ''", name=op.f("ck_companies_normalized_name_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_companies_user_id_id")),
        sa.UniqueConstraint(
            "user_id", "normalized_name", name=op.f("uq_companies_user_id_normalized_name")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_companies_user_id_users"), ondelete="CASCADE"
        ),
    )

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("team", sa.Text(), nullable=True),
        sa.Column("external_job_id", sa.Text(), nullable=True),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("locations", postgresql.JSONB(), nullable=False),
        sa.Column("workplace_type", sa.Text(), server_default="unspecified", nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("jd_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="new", nullable=False),
        sa.Column("priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column("extraction_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("extraction_error_code", sa.Text(), nullable=True),
        sa.Column("llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("latest_evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        timestamp("content_updated_at"),
        timestamp("discovered_at"),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "status IN ('new', 'saved', 'skipped', 'applied', 'closed')",
            name=op.f("ck_opportunities_status"),
        ),
        sa.CheckConstraint(
            "priority IN ('high', 'normal', 'low')", name=op.f("ck_opportunities_priority")
        ),
        sa.CheckConstraint(
            "extraction_status IN ('pending', 'succeeded', 'failed')",
            name=op.f("ck_opportunities_extraction_status"),
        ),
        sa.CheckConstraint(
            "workplace_type IN ('onsite', 'hybrid', 'remote', 'unspecified')",
            name=op.f("ck_opportunities_workplace_type"),
        ),
        sa.CheckConstraint("source IN ('manual_paste')", name=op.f("ck_opportunities_source")),
        sa.CheckConstraint(
            "(extraction_status = 'failed') = (extraction_error_code IS NOT NULL)",
            name=op.f("ck_opportunities_extraction_error_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locations) = 'object'", name=op.f("ck_opportunities_locations_object")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_opportunities_user_id_id")),
        sa.UniqueConstraint("jd_artifact_id", name=op.f("uq_opportunities_jd_artifact_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_opportunities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "company_id"],
            ["companies.user_id", "companies.id"],
            name=op.f("fk_opportunities_user_id_company_id_companies"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "jd_artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            name=op.f("fk_opportunities_user_id_jd_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "llm_run_id"],
            ["llm_runs.user_id", "llm_runs.id"],
            name=op.f("fk_opportunities_user_id_llm_run_id_llm_runs"),
        ),
    )
    op.create_index(
        "uq_opportunities_company_external_job_id",
        "opportunities",
        ["user_id", "company_id", "external_job_id"],
        unique=True,
        postgresql_where=sa.text("external_job_id IS NOT NULL AND company_id IS NOT NULL"),
    )
    op.create_index(
        "ix_opportunities_user_id_discovered_at", "opportunities", ["user_id", "discovered_at"]
    )
    op.create_index(
        "ix_opportunities_user_id_company_id", "opportunities", ["user_id", "company_id"]
    )

    op.create_table(
        "qualifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text_verbatim", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "skill_keys", postgresql.ARRAY(sa.Text()), server_default=EMPTY_ARRAY, nullable=False
        ),
        sa.Column("min_years", sa.Integer(), nullable=True),
        sa.Column(
            "is_hard_constraint", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.Uuid(), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint("kind IN ('minimum', 'preferred')", name=op.f("ck_qualifications_kind")),
        sa.CheckConstraint(
            "category IN ('skill', 'experience', 'education', 'domain', 'authorization', "
            "'location', 'other')",
            name=op.f("ck_qualifications_category"),
        ),
        sa.CheckConstraint(
            "origin IN ('extracted', 'user')", name=op.f("ck_qualifications_origin")
        ),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_qualifications_ordinal_nonnegative")),
        sa.CheckConstraint(
            "char_length(text_verbatim) BETWEEN 1 AND 2000",
            name=op.f("ck_qualifications_text_verbatim_length"),
        ),
        sa.CheckConstraint(
            "min_years IS NULL OR min_years BETWEEN 0 AND 50",
            name=op.f("ck_qualifications_min_years_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qualifications")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_qualifications_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_qualifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "opportunity_id"],
            ["opportunities.user_id", "opportunities.id"],
            name=op.f("fk_qualifications_user_id_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "llm_run_id"],
            ["llm_runs.user_id", "llm_runs.id"],
            name=op.f("fk_qualifications_user_id_llm_run_id_llm_runs"),
        ),
    )
    op.create_index(
        "ix_qualifications_user_id_opportunity_id",
        "qualifications",
        ["user_id", "opportunity_id"],
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON companies TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON opportunities TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON qualifications TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (kind, ordinal, category, skill_keys, min_years, is_hard_constraint, "
        f"updated_at) ON qualifications TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("qualifications")
    op.drop_table("opportunities")
    op.drop_table("companies")
