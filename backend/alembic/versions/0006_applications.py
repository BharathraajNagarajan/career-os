"""applications

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"
TERMINAL = "'rejected', 'withdrawn', 'accepted', 'declined', 'no_response'"


def timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=True),
        sa.Column("lane_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.Text(), server_default="other", nullable=False),
        sa.Column("stage", sa.Text(), server_default="applied", nullable=False),
        sa.Column("is_terminal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.CheckConstraint(
            "stage IN ('applied', 'assessment', 'interviewing', 'offer', 'rejected', "
            f"'withdrawn', 'accepted', 'declined', 'no_response')",
            name=op.f("ck_applications_stage"),
        ),
        sa.CheckConstraint(
            "channel IN ('company_site', 'job_board', 'referral', 'recruiter', 'email', 'other')",
            name=op.f("ck_applications_channel"),
        ),
        sa.CheckConstraint(
            f"is_terminal = (stage IN ({TERMINAL}))",
            name=op.f("ck_applications_terminal_matches_stage"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_applications_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_applications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "opportunity_id"],
            ["opportunities.user_id", "opportunities.id"],
            name=op.f("fk_applications_user_id_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "resume_id"],
            ["resumes.user_id", "resumes.id"],
            name=op.f("fk_applications_user_id_resume_id_resumes"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "lane_id"],
            ["resume_lanes.user_id", "resume_lanes.id"],
            name=op.f("fk_applications_user_id_lane_id_resume_lanes"),
        ),
    )
    op.create_index(
        "uq_applications_open_per_opportunity",
        "applications",
        ["user_id", "opportunity_id"],
        unique=True,
        postgresql_where=sa.text("NOT is_terminal"),
    )
    op.create_index(
        "ix_applications_user_id_opportunity_id", "applications", ["user_id", "opportunity_id"]
    )
    op.create_index("ix_applications_user_id_applied_at", "applications", ["user_id", "applied_at"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON applications TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("applications")
