"""add Discord homework spaces

Revision ID: 0a1b2c3d4e5f
Revises: f6a7b8c9d0e1
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_homework_spaces",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_discord_homework_spaces_student_id_students"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discord_homework_spaces")),
        sa.UniqueConstraint(
            "channel_id", name="discord_homework_channel"
        ),
        sa.UniqueConstraint(
            "guild_id", "discord_user_id", name="discord_guild_user"
        ),
    )
    op.create_index(
        op.f("ix_discord_homework_spaces_discord_user_id"),
        "discord_homework_spaces",
        ["discord_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discord_homework_spaces_guild_id"),
        "discord_homework_spaces",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discord_homework_spaces_student_id"),
        "discord_homework_spaces",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_discord_homework_spaces_student_id"),
        table_name="discord_homework_spaces",
    )
    op.drop_index(
        op.f("ix_discord_homework_spaces_guild_id"),
        table_name="discord_homework_spaces",
    )
    op.drop_index(
        op.f("ix_discord_homework_spaces_discord_user_id"),
        table_name="discord_homework_spaces",
    )
    op.drop_table("discord_homework_spaces")
