"""add Discord lesson dispatches

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a7b8c9d0e1f"
down_revision: str | None = "5f6a7b8c9d0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_lesson_dispatches",
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_staff_id", sa.Uuid(), nullable=False),
        sa.Column("custom_message", sa.Text(), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_staff_id"], ["staff_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discord_lesson_dispatches_lesson_id", "discord_lesson_dispatches", ["lesson_id"]
    )
    op.create_index(
        "ix_discord_lesson_dispatches_created_by_staff_id",
        "discord_lesson_dispatches",
        ["created_by_staff_id"],
    )
    op.create_table(
        "discord_lesson_deliveries",
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=7), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discord_message_id", sa.BigInteger(), nullable=True),
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
            ["dispatch_id"], ["discord_lesson_dispatches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["discord_student_links.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lesson_id", "participant_id", name="discord_lesson_participant_delivery"
        ),
    )
    op.create_index(
        "ix_discord_lesson_deliveries_dispatch_id", "discord_lesson_deliveries", ["dispatch_id"]
    )
    op.create_index(
        "ix_discord_lesson_deliveries_lesson_id", "discord_lesson_deliveries", ["lesson_id"]
    )
    op.create_index(
        "ix_discord_lesson_deliveries_participant_id",
        "discord_lesson_deliveries",
        ["participant_id"],
    )
    op.create_index("ix_discord_lesson_deliveries_status", "discord_lesson_deliveries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_discord_lesson_deliveries_status", table_name="discord_lesson_deliveries")
    op.drop_index(
        "ix_discord_lesson_deliveries_participant_id", table_name="discord_lesson_deliveries"
    )
    op.drop_index("ix_discord_lesson_deliveries_lesson_id", table_name="discord_lesson_deliveries")
    op.drop_index(
        "ix_discord_lesson_deliveries_dispatch_id", table_name="discord_lesson_deliveries"
    )
    op.drop_table("discord_lesson_deliveries")
    op.drop_index(
        "ix_discord_lesson_dispatches_created_by_staff_id", table_name="discord_lesson_dispatches"
    )
    op.drop_index("ix_discord_lesson_dispatches_lesson_id", table_name="discord_lesson_dispatches")
    op.drop_table("discord_lesson_dispatches")
