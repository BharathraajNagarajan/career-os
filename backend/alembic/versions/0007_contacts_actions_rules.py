"""contacts, links, interactions, recruiting actions, strategy rules

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
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
        "contacts",
        *owner_columns(),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("emails", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("source", sa.Text(), server_default="manual", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            in_list("source", ["manual", "gmail", "import"]), name=op.f("ck_contacts_source")
        ),
        sa.CheckConstraint(
            "char_length(full_name) BETWEEN 1 AND 200", name=op.f("ck_contacts_full_name_length")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(emails) = 'object'", name=op.f("ck_contacts_emails_object")
        ),
        sa.CheckConstraint("char_length(notes) <= 5000", name=op.f("ck_contacts_notes_length")),
        *owner_constraints("contacts"),
    )
    op.create_index("ix_contacts_emails", "contacts", ["emails"], postgresql_using="gin")
    op.create_index("ix_contacts_user_id_created_at", "contacts", ["user_id", "created_at"])

    op.create_table(
        "contact_companies",
        *owner_columns(),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.Text(), server_default="other", nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        timestamp("created_at"),
        sa.CheckConstraint(
            in_list(
                "relation",
                ["employee", "recruiter", "former_employee", "agency_recruiter", "other"],
            ),
            name=op.f("ck_contact_companies_relation"),
        ),
        sa.CheckConstraint(
            "title IS NULL OR char_length(title) <= 200",
            name=op.f("ck_contact_companies_title_length"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "contact_id",
            "company_id",
            name=op.f("uq_contact_companies_user_id_contact_id_company_id"),
        ),
        owned_fk("contact_companies", "contact_id", "contacts"),
        owned_fk("contact_companies", "company_id", "companies"),
        *owner_constraints("contact_companies"),
    )
    op.create_index(
        "ix_contact_companies_user_id_company_id", "contact_companies", ["user_id", "company_id"]
    )

    op.create_table(
        "contact_opportunities",
        *owner_columns(),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        timestamp("created_at"),
        sa.CheckConstraint(
            in_list(
                "role",
                ["recruiter", "hiring_manager", "referrer", "interviewer", "team_member", "other"],
            ),
            name=op.f("ck_contact_opportunities_role"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "contact_id",
            "opportunity_id",
            "role",
            name=op.f("uq_contact_opportunities_user_id_contact_id_opportunity_id_role"),
        ),
        owned_fk("contact_opportunities", "contact_id", "contacts"),
        owned_fk("contact_opportunities", "opportunity_id", "opportunities"),
        *owner_constraints("contact_opportunities"),
    )
    op.create_index(
        "ix_contact_opportunities_user_id_opportunity_id",
        "contact_opportunities",
        ["user_id", "opportunity_id"],
    )

    op.create_table(
        "interactions",
        *owner_columns(),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("external_ref_id", sa.Uuid(), nullable=True),
        timestamp("created_at"),
        sa.CheckConstraint(
            in_list("channel", ["email", "linkedin", "phone", "in_person", "other"]),
            name=op.f("ck_interactions_channel"),
        ),
        sa.CheckConstraint(
            in_list("direction", ["inbound", "outbound"]), name=op.f("ck_interactions_direction")
        ),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) <= 2000",
            name=op.f("ck_interactions_summary_length"),
        ),
        owned_fk("interactions", "contact_id", "contacts"),
        owned_fk("interactions", "company_id", "companies"),
        owned_fk("interactions", "opportunity_id", "opportunities"),
        owned_fk("interactions", "application_id", "applications"),
        owned_fk("interactions", "artifact_id", "artifacts"),
        *owner_constraints("interactions"),
    )
    op.create_index(
        "ix_interactions_user_id_contact_id_occurred_at",
        "interactions",
        ["user_id", "contact_id", "occurred_at"],
    )
    op.create_index(
        "ix_interactions_user_id_opportunity_id", "interactions", ["user_id", "opportunity_id"]
    )
    op.create_index(
        "ix_interactions_user_id_application_id", "interactions", ["user_id", "application_id"]
    )

    op.create_table(
        "recruiting_actions",
        *owner_columns(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("interaction_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("recommendation_llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("draft_subject", sa.Text(), nullable=True),
        sa.Column("draft_body", sa.Text(), nullable=True),
        sa.Column("draft_llm_run_id", sa.Uuid(), nullable=True),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            in_list(
                "kind",
                [
                    "follow_up",
                    "reply",
                    "complete_assessment",
                    "attend_interview",
                    "schedule_interview",
                    "outreach",
                    "custom",
                ],
            ),
            name=op.f("ck_recruiting_actions_kind"),
        ),
        sa.CheckConstraint(
            in_list("status", ["open", "snoozed", "done", "dismissed", "superseded"]),
            name=op.f("ck_recruiting_actions_status"),
        ),
        sa.CheckConstraint(
            in_list("origin", ["user", "extracted", "chat", "gmail", "system"]),
            name=op.f("ck_recruiting_actions_origin"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name=op.f("ck_recruiting_actions_title_length")
        ),
        sa.CheckConstraint(
            "sequence_no >= 1", name=op.f("ck_recruiting_actions_sequence_no_positive")
        ),
        sa.CheckConstraint(
            "(status = 'snoozed') = (snoozed_until IS NOT NULL)",
            name=op.f("ck_recruiting_actions_snooze_consistent"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('attend_interview', 'complete_assessment') OR due_at IS NOT NULL",
            name=op.f("ck_recruiting_actions_scheduled_kinds_have_due_at"),
        ),
        sa.CheckConstraint(
            "kind = 'outreach' OR (recommendation_llm_run_id IS NULL AND draft_subject IS NULL "
            "AND draft_body IS NULL AND draft_llm_run_id IS NULL AND draft_updated_at IS NULL)",
            name=op.f("ck_recruiting_actions_draft_only_for_outreach"),
        ),
        owned_fk("recruiting_actions", "opportunity_id", "opportunities"),
        owned_fk("recruiting_actions", "application_id", "applications"),
        owned_fk("recruiting_actions", "contact_id", "contacts"),
        owned_fk("recruiting_actions", "interaction_id", "interactions"),
        owned_fk("recruiting_actions", "recommendation_llm_run_id", "llm_runs"),
        owned_fk("recruiting_actions", "draft_llm_run_id", "llm_runs"),
        *owner_constraints("recruiting_actions"),
    )
    op.create_index(
        "ix_recruiting_actions_user_id_status_due_at",
        "recruiting_actions",
        ["user_id", "status", "due_at"],
    )
    op.create_index(
        "ix_recruiting_actions_user_id_opportunity_id",
        "recruiting_actions",
        ["user_id", "opportunity_id"],
    )
    op.create_index(
        "ix_recruiting_actions_user_id_application_id",
        "recruiting_actions",
        ["user_id", "application_id"],
    )
    op.create_index(
        "ix_recruiting_actions_user_id_contact_id", "recruiting_actions", ["user_id", "contact_id"]
    )

    op.create_table(
        "strategy_rules",
        *owner_columns(),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("lane_id", sa.Uuid(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("condition", postgresql.JSONB(none_as_null=True, astext_type=sa.Text())),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            in_list("scope", ["global", "company", "lane"]), name=op.f("ck_strategy_rules_scope")
        ),
        sa.CheckConstraint(
            in_list("rule_type", ["constraint", "preference", "cooldown"]),
            name=op.f("ck_strategy_rules_rule_type"),
        ),
        sa.CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 1000",
            name=op.f("ck_strategy_rules_statement_length"),
        ),
        sa.CheckConstraint(
            "condition IS NULL OR jsonb_typeof(condition) = 'object'",
            name=op.f("ck_strategy_rules_condition_object"),
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND company_id IS NULL AND lane_id IS NULL) OR "
            "(scope = 'company' AND company_id IS NOT NULL AND lane_id IS NULL) OR "
            "(scope = 'lane' AND lane_id IS NOT NULL AND company_id IS NULL)",
            name=op.f("ck_strategy_rules_scope_matches_target"),
        ),
        owned_fk("strategy_rules", "company_id", "companies"),
        owned_fk("strategy_rules", "lane_id", "resume_lanes"),
        *owner_constraints("strategy_rules"),
    )
    op.create_index("ix_strategy_rules_user_id_scope", "strategy_rules", ["user_id", "scope"])

    for table in ("contacts", "recruiting_actions"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT DELETE ON contacts TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON interactions TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (contact_id) ON interactions TO {APP_ROLE}")
    for table in ("contact_companies", "contact_opportunities", "strategy_rules"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in (
        "strategy_rules",
        "recruiting_actions",
        "interactions",
        "contact_opportunities",
        "contact_companies",
        "contacts",
    ):
        op.drop_table(table)
