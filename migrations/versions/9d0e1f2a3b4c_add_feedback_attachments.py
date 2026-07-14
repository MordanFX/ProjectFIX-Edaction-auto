"""Add curator feedback attachments.

Revision ID: 9d0e1f2a3b4c
Revises: 0f1a2b3c4d5e
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d0e1f2a3b4c"
down_revision: str | None = "0f1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_attachments",
        sa.Column("feedback_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum(
            "document",
            "photo",
            "video",
            "video_note",
            name="feedback_attachment_kind",
            native_enum=False,
            length=32,
        ), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=512), nullable=True),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=True),
        sa.Column("discord_attachment_id", sa.BigInteger(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_feedback_attachments_discord_attachment_id"),
        "feedback_attachments",
        ["discord_attachment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_attachments_feedback_id"),
        "feedback_attachments",
        ["feedback_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_attachments_telegram_file_unique_id"),
        "feedback_attachments",
        ["telegram_file_unique_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_feedback_attachments_telegram_file_unique_id"),
        table_name="feedback_attachments",
    )
    op.drop_index(
        op.f("ix_feedback_attachments_feedback_id"),
        table_name="feedback_attachments",
    )
    op.drop_index(
        op.f("ix_feedback_attachments_discord_attachment_id"),
        table_name="feedback_attachments",
    )
    op.drop_table("feedback_attachments")
