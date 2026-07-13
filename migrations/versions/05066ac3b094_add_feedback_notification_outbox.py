"""add feedback notification outbox

Revision ID: 05066ac3b094
Revises: 5d85c88a25c0
Create Date: 2026-06-30 17:57:48.336713
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "05066ac3b094"
down_revision: str | None = "5d85c88a25c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    notification_status = sa.Enum(
        "pending",
        "sent",
        "failed",
        name="notification_status",
        native_enum=False,
        length=16,
    )
    op.add_column(
        "feedback",
        sa.Column("notification_status", notification_status, nullable=True),
    )
    op.add_column("feedback", sa.Column("notification_attempts", sa.Integer(), nullable=True))
    op.add_column(
        "feedback",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("feedback", sa.Column("notification_error", sa.Text(), nullable=True))
    op.execute(
        sa.text("UPDATE feedback SET notification_status = 'sent', notification_attempts = 0")
    )
    with op.batch_alter_table("feedback") as batch_op:
        batch_op.alter_column(
            "notification_status",
            existing_type=notification_status,
            nullable=False,
        )
        batch_op.alter_column(
            "notification_attempts",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_index(
            op.f("ix_feedback_notification_status"),
            ["notification_status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("feedback") as batch_op:
        batch_op.drop_index(op.f("ix_feedback_notification_status"))
        batch_op.drop_column("notification_error")
        batch_op.drop_column("notified_at")
        batch_op.drop_column("notification_attempts")
        batch_op.drop_column("notification_status")
