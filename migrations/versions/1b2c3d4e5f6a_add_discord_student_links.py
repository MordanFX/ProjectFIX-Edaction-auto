"""add Discord student links and one-time codes

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1b2c3d4e5f6a"
down_revision: str | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_link_codes",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discord_link_codes")),
    )
    op.create_index(
        op.f("ix_discord_link_codes_code_digest"),
        "discord_link_codes",
        ["code_digest"],
        unique=True,
    )
    op.create_index(
        op.f("ix_discord_link_codes_expires_at"), "discord_link_codes", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_discord_link_codes_student_id"), "discord_link_codes", ["student_id"], unique=False
    )

    op.create_table(
        "discord_student_links",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discord_student_links")),
        sa.UniqueConstraint("guild_id", "discord_user_id", name="discord_link_guild_user"),
        sa.UniqueConstraint("guild_id", "student_id", name="discord_link_guild_student"),
    )
    op.create_index(
        op.f("ix_discord_student_links_discord_user_id"),
        "discord_student_links",
        ["discord_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discord_student_links_guild_id"),
        "discord_student_links",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discord_student_links_student_id"),
        "discord_student_links",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_discord_student_links_student_id"), table_name="discord_student_links")
    op.drop_index(op.f("ix_discord_student_links_guild_id"), table_name="discord_student_links")
    op.drop_index(
        op.f("ix_discord_student_links_discord_user_id"), table_name="discord_student_links"
    )
    op.drop_table("discord_student_links")
    op.drop_index(op.f("ix_discord_link_codes_student_id"), table_name="discord_link_codes")
    op.drop_index(op.f("ix_discord_link_codes_expires_at"), table_name="discord_link_codes")
    op.drop_index(op.f("ix_discord_link_codes_code_digest"), table_name="discord_link_codes")
    op.drop_table("discord_link_codes")
