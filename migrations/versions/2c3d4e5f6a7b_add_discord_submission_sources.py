"""add Discord submission sources

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c3d4e5f6a7b"
down_revision: str | None = "1b2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source",
                sa.Enum("telegram", "discord", name="submission_source", native_enum=False),
                server_default="telegram",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("source_guild_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("source_channel_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("source_message_id", sa.BigInteger(), nullable=True))
        batch_op.create_index("ix_submissions_source", ["source"], unique=False)
        batch_op.create_unique_constraint(
            "discord_submission_message",
            ["source_channel_id", "source_message_id"],
        )

    with op.batch_alter_table("submission_attachments") as batch_op:
        batch_op.alter_column(
            "telegram_file_id",
            existing_type=sa.String(length=512),
            nullable=True,
        )
        batch_op.alter_column(
            "telegram_file_unique_id",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("discord_attachment_id", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(sa.Column("external_url", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_submission_attachments_discord_attachment_id",
            ["discord_attachment_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("submission_attachments") as batch_op:
        batch_op.drop_index("ix_submission_attachments_discord_attachment_id")
        batch_op.drop_column("external_url")
        batch_op.drop_column("discord_attachment_id")
        batch_op.alter_column(
            "telegram_file_unique_id",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.alter_column(
            "telegram_file_id",
            existing_type=sa.String(length=512),
            nullable=False,
        )

    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_constraint("discord_submission_message", type_="unique")
        batch_op.drop_index("ix_submissions_source")
        batch_op.drop_column("source_message_id")
        batch_op.drop_column("source_channel_id")
        batch_op.drop_column("source_guild_id")
        batch_op.drop_column("source")
