"""add durable Telegram curator review state

Revision ID: c1d2e3f4a5b6
Revises: b73ac912de40
Create Date: 2026-07-01 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b73ac912de40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_bot_states",
        sa.Column("staff_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "revision_requested",
                "accepted",
                name="feedback_verdict",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff_users.id"],
            name=op.f("fk_staff_bot_states_staff_id_staff_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_staff_bot_states_submission_id_submissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("staff_id", name=op.f("pk_staff_bot_states")),
    )
    op.create_index(
        op.f("ix_staff_bot_states_submission_id"),
        "staff_bot_states",
        ["submission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_staff_bot_states_submission_id"),
        table_name="staff_bot_states",
    )
    op.drop_table("staff_bot_states")
