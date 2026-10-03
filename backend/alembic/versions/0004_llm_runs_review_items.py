"""llm_runs, review_items

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"


def upgrade() -> None:
    op.create_table(
        "llm_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("repair_of_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("reserved_cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("context_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('extract_resume', 'extract_jd', 'classify_email', 'evaluate', 'chat', "
            "'propose_skill_evidence', 'outreach_recommendation', 'outreach_draft')",
            name=op.f("ck_llm_runs_purpose"),
        ),
        sa.CheckConstraint("tier IN ('fast', 'reasoning')", name=op.f("ck_llm_runs_tier")),
        sa.CheckConstraint("provider IN ('fake', 'anthropic')", name=op.f("ck_llm_runs_provider")),
        sa.CheckConstraint(
            "status IN ('reserved', 'succeeded', 'failed')", name=op.f("ck_llm_runs_status")
        ),
        sa.CheckConstraint("attempt IN (1, 2)", name=op.f("ck_llm_runs_attempt")),
        sa.CheckConstraint(
            "(attempt = 1) = (repair_of_run_id IS NULL)", name=op.f("ck_llm_runs_repair_link")
        ),
        sa.CheckConstraint(
            "max_output_tokens > 0", name=op.f("ck_llm_runs_max_output_tokens_positive")
        ),
        sa.CheckConstraint(
            "reserved_cost_usd >= 0", name=op.f("ck_llm_runs_reserved_cost_nonnegative")
        ),
        sa.CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0", name=op.f("ck_llm_runs_cost_nonnegative")
        ),
        sa.CheckConstraint(
            "(status = 'reserved') = (cost_usd IS NULL) AND "
            "(status = 'reserved') = (settled_at IS NULL)",
            name=op.f("ck_llm_runs_settlement_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(context_manifest) = 'object'",
            name=op.f("ck_llm_runs_manifest_object"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_runs")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_llm_runs_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_llm_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "repair_of_run_id"],
            ["llm_runs.user_id", "llm_runs.id"],
            name=op.f("fk_llm_runs_user_id_repair_of_run_id_llm_runs"),
        ),
    )
    op.create_index("ix_llm_runs_user_id_created_at", "llm_runs", ["user_id", "created_at"])

    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("proposal_type", sa.Text(), nullable=False),
        sa.Column("proposed_payload", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence_ref_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("decided_payload", postgresql.JSONB(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('gmail', 'extraction', 'chat')", name=op.f("ck_review_items_source")
        ),
        sa.CheckConstraint(
            "proposal_type IN ('claim', 'skill', 'skill_evidence', 'create_application', "
            "'application_event', 'interaction', 'contact_link', 'contact_email')",
            name=op.f("ck_review_items_proposal_type"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'expired')",
            name=op.f("ck_review_items_status"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_review_items_confidence_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_payload) = 'object'",
            name=op.f("ck_review_items_proposed_payload_object"),
        ),
        sa.CheckConstraint(
            "decided_payload IS NULL OR jsonb_typeof(decided_payload) = 'object'",
            name=op.f("ck_review_items_decided_payload_object"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_review_items_decision_consistent"),
        ),
        sa.CheckConstraint(
            "decided_payload IS NULL OR status = 'confirmed'",
            name=op.f("ck_review_items_decided_payload_confirmed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_items")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_review_items_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_review_items_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "llm_run_id"],
            ["llm_runs.user_id", "llm_runs.id"],
            name=op.f("fk_review_items_user_id_llm_run_id_llm_runs"),
        ),
    )
    op.create_index(
        "ix_review_items_user_id_status_created_at",
        "review_items",
        ["user_id", "status", "created_at"],
    )

    op.execute(f"GRANT SELECT, INSERT ON llm_runs TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (status, error_code, input_tokens, output_tokens, latency_ms, cost_usd, "
        f"output, settled_at) ON llm_runs TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON review_items TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (status, decided_at, decided_payload, decision_note, state_version, "
        f"updated_at) ON review_items TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("llm_runs")
