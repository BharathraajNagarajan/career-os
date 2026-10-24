"""skills, claims, evidence sources, claim-skill links

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"


def timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def owner_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
    ]


def owner_constraints(table: str) -> list[sa.schema.SchemaItem]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("user_id", "id", name=op.f(f"uq_{table}_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
        ),
    ]


def owned_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id", column],
        [f"{target}.user_id", f"{target}.id"],
        name=op.f(f"fk_{table}_user_id_{column}_{target}"),
    )


def in_list(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "skills",
        *owner_columns(),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("confirmation_status", sa.Text(), server_default="confirmed", nullable=False),
        sa.Column("user_marked_gap", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gap_note", sa.Text(), nullable=True),
        sa.Column("user_note", sa.Text(), server_default="", nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("merged_into_skill_id", sa.Uuid(), nullable=True),
        sa.Column("llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            in_list("confirmation_status", ["proposed", "confirmed", "rejected"]),
            name=op.f("ck_skills_confirmation_status"),
        ),
        sa.CheckConstraint(
            in_list("origin", ["user", "extracted", "chat"]), name=op.f("ck_skills_origin")
        ),
        sa.CheckConstraint(
            "char_length(canonical_name) BETWEEN 1 AND 100",
            name=op.f("ck_skills_canonical_name_length"),
        ),
        sa.CheckConstraint("normalized_key <> ''", name=op.f("ck_skills_normalized_key_not_empty")),
        sa.CheckConstraint("cardinality(aliases) <= 50", name=op.f("ck_skills_aliases_count")),
        sa.CheckConstraint(
            "char_length(user_note) <= 2000", name=op.f("ck_skills_user_note_length")
        ),
        sa.CheckConstraint(
            "gap_note IS NULL OR char_length(gap_note) <= 2000",
            name=op.f("ck_skills_gap_note_length"),
        ),
        sa.CheckConstraint(
            "user_marked_gap OR gap_note IS NULL", name=op.f("ck_skills_gap_note_needs_gap")
        ),
        sa.CheckConstraint(
            "merged_into_skill_id IS NULL OR merged_into_skill_id <> id",
            name=op.f("ck_skills_merge_not_self"),
        ),
        sa.CheckConstraint(
            "merged_into_skill_id IS NULL OR NOT user_marked_gap",
            name=op.f("ck_skills_merged_has_no_gap"),
        ),
        owned_fk("skills", "merged_into_skill_id", "skills"),
        owned_fk("skills", "llm_run_id", "llm_runs"),
        *owner_constraints("skills"),
    )
    op.create_index(
        "uq_skills_user_id_normalized_key",
        "skills",
        ["user_id", "normalized_key"],
        unique=True,
        postgresql_where=sa.text("merged_into_skill_id IS NULL"),
    )
    op.create_index("ix_skills_user_id_updated_at", "skills", ["user_id", "updated_at"])

    op.create_table(
        "claims",
        *owner_columns(),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_class", sa.Text(), nullable=False),
        sa.Column("engagement_type", sa.Text(), nullable=True),
        sa.Column("confirmation_status", sa.Text(), server_default="confirmed", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("organization_label", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            in_list("evidence_class", ["professional", "academic_research", "project", "learning"]),
            name=op.f("ck_claims_evidence_class"),
        ),
        sa.CheckConstraint(
            in_list(
                "engagement_type",
                ["full_time", "part_time", "contract", "internship", "unspecified"],
            ),
            name=op.f("ck_claims_engagement_type"),
        ),
        sa.CheckConstraint(
            in_list("confirmation_status", ["proposed", "confirmed", "rejected"]),
            name=op.f("ck_claims_confirmation_status"),
        ),
        sa.CheckConstraint(
            in_list("origin", ["user", "extracted", "chat"]), name=op.f("ck_claims_origin")
        ),
        sa.CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 2000", name=op.f("ck_claims_statement_length")
        ),
        sa.CheckConstraint(
            "organization_label IS NULL OR char_length(organization_label) BETWEEN 1 AND 200",
            name=op.f("ck_claims_organization_label_length"),
        ),
        sa.CheckConstraint(
            "(evidence_class = 'professional') = (engagement_type IS NOT NULL)",
            name=op.f("ck_claims_engagement_type_only_professional"),
        ),
        sa.CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_claims_dates_ordered"),
        ),
        owned_fk("claims", "llm_run_id", "llm_runs"),
        *owner_constraints("claims"),
    )
    op.create_index("ix_claims_user_id_evidence_class", "claims", ["user_id", "evidence_class"])
    op.create_index("ix_claims_user_id_created_at", "claims", ["user_id", "created_at"])

    op.create_table(
        "evidence_sources",
        *owner_columns(),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("assertion_text", sa.Text(), nullable=True),
        timestamp("created_at"),
        sa.CheckConstraint(
            in_list("source_type", ["resume", "project_url", "user_assertion", "artifact"]),
            name=op.f("ck_evidence_sources_source_type"),
        ),
        sa.CheckConstraint(
            "(source_type IN ('resume', 'artifact')) = (artifact_id IS NOT NULL)",
            name=op.f("ck_evidence_sources_artifact_only_for_file_sources"),
        ),
        sa.CheckConstraint(
            "(source_type = 'project_url') = (url IS NOT NULL)",
            name=op.f("ck_evidence_sources_url_only_for_project_url"),
        ),
        sa.CheckConstraint(
            "(source_type = 'user_assertion') = (assertion_text IS NOT NULL)",
            name=op.f("ck_evidence_sources_assertion_only_for_user_assertion"),
        ),
        sa.CheckConstraint(
            "message_id IS NULL OR source_type = 'user_assertion'",
            name=op.f("ck_evidence_sources_message_scope"),
        ),
        sa.CheckConstraint(
            "locator IS NULL OR char_length(locator) <= 500",
            name=op.f("ck_evidence_sources_locator_length"),
        ),
        sa.CheckConstraint(
            "url IS NULL OR char_length(url) <= 2000", name=op.f("ck_evidence_sources_url_length")
        ),
        sa.CheckConstraint(
            "assertion_text IS NULL OR char_length(assertion_text) BETWEEN 1 AND 2000",
            name=op.f("ck_evidence_sources_assertion_text_length"),
        ),
        owned_fk("evidence_sources", "claim_id", "claims"),
        owned_fk("evidence_sources", "artifact_id", "artifacts"),
        *owner_constraints("evidence_sources"),
    )
    op.create_index(
        "ix_evidence_sources_user_id_claim_id", "evidence_sources", ["user_id", "claim_id"]
    )
    op.create_index(
        "ix_evidence_sources_user_id_artifact_id", "evidence_sources", ["user_id", "artifact_id"]
    )

    op.create_table(
        "claim_skills",
        *owner_columns(),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        timestamp("created_at"),
        sa.UniqueConstraint(
            "user_id",
            "claim_id",
            "skill_id",
            name=op.f("uq_claim_skills_user_id_claim_id_skill_id"),
        ),
        owned_fk("claim_skills", "claim_id", "claims"),
        owned_fk("claim_skills", "skill_id", "skills"),
        *owner_constraints("claim_skills"),
    )
    op.create_index("ix_claim_skills_user_id_skill_id", "claim_skills", ["user_id", "skill_id"])

    op.execute(
        f"GRANT SELECT, INSERT ON skills, claims, evidence_sources, claim_skills TO {APP_ROLE}"
    )
    op.execute(
        "GRANT UPDATE (canonical_name, normalized_key, aliases, confirmation_status, "
        "user_marked_gap, gap_note, user_note, merged_into_skill_id, state_version, updated_at) "
        f"ON skills TO {APP_ROLE}"
    )
    op.execute(
        "GRANT UPDATE (statement, evidence_class, engagement_type, confirmation_status, "
        "start_date, end_date, organization_label, state_version, updated_at) "
        f"ON claims TO {APP_ROLE}"
    )
    op.execute(f"GRANT UPDATE (skill_id) ON claim_skills TO {APP_ROLE}")
    op.execute(f"GRANT DELETE ON claim_skills TO {APP_ROLE}")


def downgrade() -> None:
    for table in ("claim_skills", "evidence_sources", "claims", "skills"):
        op.drop_table(table)
