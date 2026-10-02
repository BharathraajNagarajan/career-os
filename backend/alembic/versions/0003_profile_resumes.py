"""profiles, artifacts, resumes, resume_lanes

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"


def created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("current_location", sa.Text(), nullable=True),
        sa.Column(
            "relocation_preference", sa.Text(), server_default="unspecified", nullable=False
        ),
        sa.Column("remote_preference", sa.Text(), server_default="no_preference", nullable=False),
        sa.Column("work_authorization", postgresql.JSONB(), nullable=False),
        sa.Column(
            "constraints_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("target_roles", postgresql.JSONB(), nullable=False),
        sa.Column("communication_preferences", postgresql.JSONB(), nullable=False),
        created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "relocation_preference IN ('open', 'not_open', 'unspecified')",
            name=op.f("ck_profiles_relocation_preference"),
        ),
        sa.CheckConstraint(
            "remote_preference IN ('remote_only', 'hybrid', 'onsite', 'no_preference')",
            name=op.f("ck_profiles_remote_preference"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_profiles_user_id_id")),
        sa.UniqueConstraint("user_id", name=op.f("uq_profiles_user_id")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_profiles_user_id_users"), ondelete="CASCADE"
        ),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("extraction_error_code", sa.Text(), nullable=True),
        created_at(),
        sa.CheckConstraint(
            "kind IN ('resume_file', 'jd_snapshot', 'email_excerpt', 'reference')",
            name=op.f("ck_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "extraction_status IN ('pending', 'succeeded', 'failed')",
            name=op.f("ck_artifacts_extraction_status"),
        ),
        sa.CheckConstraint("octet_length(sha256) = 32", name=op.f("ck_artifacts_sha256_length")),
        sa.CheckConstraint("byte_size >= 0", name=op.f("ck_artifacts_byte_size_nonnegative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_artifacts_user_id_id")),
        sa.UniqueConstraint(
            "user_id", "sha256", "kind", name=op.f("uq_artifacts_user_id_sha256_kind")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_artifacts_user_id_users"), ondelete="CASCADE"
        ),
    )

    op.create_table(
        "resume_lanes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("emphasis_notes", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "target_role_labels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("default_resume_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_resume_lanes_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_lanes")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_resume_lanes_user_id_id")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_lanes_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_resume_lanes_active_name",
        "resume_lanes",
        ["user_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("lane_id", sa.Uuid(), nullable=True),
        sa.Column("parsed_outline", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        created_at(),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_resumes_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resumes")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_resumes_user_id_id")),
        sa.UniqueConstraint("artifact_id", name=op.f("uq_resumes_artifact_id")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_resumes_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            name=op.f("fk_resumes_user_id_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "lane_id"],
            ["resume_lanes.user_id", "resume_lanes.id"],
            name=op.f("fk_resumes_user_id_lane_id_resume_lanes"),
        ),
    )

    op.create_foreign_key(
        op.f("fk_resume_lanes_user_id_default_resume_id_resumes"),
        "resume_lanes",
        "resumes",
        ["user_id", "default_resume_id"],
        ["user_id", "id"],
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON profiles TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON artifacts TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (extracted_text, extraction_status, extraction_error_code) "
        f"ON artifacts TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON resumes TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON resume_lanes TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_resume_lanes_user_id_default_resume_id_resumes"), "resume_lanes", type_="foreignkey"
    )
    op.drop_table("resumes")
    op.drop_table("resume_lanes")
    op.drop_table("artifacts")
    op.drop_table("profiles")
