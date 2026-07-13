"""add Discord student questions

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b8c9d0e1f2a"
down_revision: str | None = "6a7b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_questions",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=True),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_staff_id", sa.Uuid(), nullable=True),
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
            ["participant_id"], ["discord_student_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["resolved_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "channel_id", "message_id", name="discord_question_message"),
    )
    op.create_index("ix_discord_questions_guild_id", "discord_questions", ["guild_id"])
    op.create_index("ix_discord_questions_channel_id", "discord_questions", ["channel_id"])
    op.create_index(
        "ix_discord_questions_discord_user_id", "discord_questions", ["discord_user_id"]
    )
    op.create_index(
        "ix_discord_questions_participant_id", "discord_questions", ["participant_id"]
    )
    op.create_index("ix_discord_questions_student_id", "discord_questions", ["student_id"])
    op.create_index("ix_discord_questions_status", "discord_questions", ["status"])
    op.create_index(
        "ix_discord_questions_resolved_by_staff_id",
        "discord_questions",
        ["resolved_by_staff_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_discord_questions_resolved_by_staff_id", table_name="discord_questions")
    op.drop_index("ix_discord_questions_status", table_name="discord_questions")
    op.drop_index("ix_discord_questions_student_id", table_name="discord_questions")
    op.drop_index("ix_discord_questions_participant_id", table_name="discord_questions")
    op.drop_index("ix_discord_questions_discord_user_id", table_name="discord_questions")
    op.drop_index("ix_discord_questions_channel_id", table_name="discord_questions")
    op.drop_index("ix_discord_questions_guild_id", table_name="discord_questions")
    op.drop_table("discord_questions")
