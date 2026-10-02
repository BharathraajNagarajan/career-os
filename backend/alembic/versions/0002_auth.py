"""auth_identities, sessions, delete_user_account

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "career_os_app"


def upgrade() -> None:
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("email_at_login", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('google')", name=op.f("ck_auth_identities_provider")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_auth_identities_user_id_id")),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name=op.f("uq_auth_identities_provider_provider_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_identities_user_id_users"),
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent_hash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_sessions_user_id_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON auth_identities TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO {APP_ROLE}")

    op.execute(
        """
        CREATE FUNCTION public.delete_user_account(target uuid) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            removed integer;
        BEGIN
            DELETE FROM public.users WHERE id = target AND status = 'deletion_requested';
            GET DIAGNOSTICS removed = ROW_COUNT;
            RETURN removed > 0;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.delete_user_account(uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.delete_user_account(uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.delete_user_account(uuid)")
    op.drop_table("sessions")
    op.drop_table("auth_identities")
