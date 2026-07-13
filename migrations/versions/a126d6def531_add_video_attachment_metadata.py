"""add video attachment metadata

Revision ID: a126d6def531
Revises: 24db613c0e55
Create Date: 2026-06-30 13:30:58.607332
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a126d6def531"
down_revision: str | None = "24db613c0e55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("submission_attachments") as batch_op:
        batch_op.add_column(sa.Column("source_chat_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("source_message_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch_op.alter_column(
            "kind",
            existing_type=sa.VARCHAR(length=8),
            type_=sa.Enum(
                "document",
                "photo",
                "video",
                "video_note",
                name="attachment_kind",
                native_enum=False,
                length=32,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("submission_attachments") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.Enum(
                "document",
                "photo",
                "video",
                "video_note",
                name="attachment_kind",
                native_enum=False,
                length=32,
            ),
            type_=sa.VARCHAR(length=8),
            existing_nullable=False,
        )
        batch_op.drop_column("height")
        batch_op.drop_column("width")
        batch_op.drop_column("duration_seconds")
        batch_op.drop_column("source_message_id")
        batch_op.drop_column("source_chat_id")
