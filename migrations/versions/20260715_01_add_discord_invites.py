"""add discord invites

Revision ID: 20260715_01
Revises: 20260714_01
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_01"
down_revision: str | None = "20260714_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_invites",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("invite_url", sa.String(length=255), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column(
            "max_age_seconds",
            sa.Integer(),
            server_default="86400",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by_staff_id"],
            ["staff_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="discord_invite_code"),
    )
    op.create_index(op.f("ix_discord_invites_code"), "discord_invites", ["code"])
    op.create_index(op.f("ix_discord_invites_course_id"), "discord_invites", ["course_id"])
    op.create_index(op.f("ix_discord_invites_expires_at"), "discord_invites", ["expires_at"])
    op.create_index(op.f("ix_discord_invites_guild_id"), "discord_invites", ["guild_id"])
    op.create_index(
        op.f("ix_discord_invites_created_by_staff_id"),
        "discord_invites",
        ["created_by_staff_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_discord_invites_created_by_staff_id"), table_name="discord_invites")
    op.drop_index(op.f("ix_discord_invites_guild_id"), table_name="discord_invites")
    op.drop_index(op.f("ix_discord_invites_expires_at"), table_name="discord_invites")
    op.drop_index(op.f("ix_discord_invites_code"), table_name="discord_invites")
    op.drop_index(op.f("ix_discord_invites_course_id"), table_name="discord_invites")
    op.drop_table("discord_invites")
