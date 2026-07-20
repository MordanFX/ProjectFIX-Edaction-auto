"""store multiple attachments per Telegram question, from student and curator

Revision ID: 20260720_04
Revises: 20260720_03
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_04"
down_revision: str | None = "20260720_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_question_attachments",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=512), nullable=True),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
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
        sa.ForeignKeyConstraint(["question_id"], ["telegram_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_question_attachments_question_id",
        "telegram_question_attachments",
        ["question_id"],
    )
    op.create_index(
        "ix_telegram_question_attachments_source",
        "telegram_question_attachments",
        ["source"],
    )
    op.create_index(
        "ix_telegram_question_attachments_telegram_file_unique_id",
        "telegram_question_attachments",
        ["telegram_file_unique_id"],
    )

    # Backfill the single attachment slot each question used to have, as the
    # student's own attachment (this was the only source before this change).
    op.execute(
        """
        INSERT INTO telegram_question_attachments
            (id, question_id, source, kind, telegram_file_id, telegram_file_unique_id,
             file_name, mime_type, file_size, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'student', attachment_kind, attachment_telegram_file_id,
               attachment_telegram_file_unique_id, attachment_file_name, attachment_mime_type,
               attachment_file_size, created_at, created_at
        FROM telegram_questions
        WHERE attachment_kind IS NOT NULL
        """
    )

    op.drop_column("telegram_questions", "attachment_kind")
    op.drop_column("telegram_questions", "attachment_telegram_file_id")
    op.drop_column("telegram_questions", "attachment_telegram_file_unique_id")
    op.drop_column("telegram_questions", "attachment_file_name")
    op.drop_column("telegram_questions", "attachment_mime_type")
    op.drop_column("telegram_questions", "attachment_file_size")


def downgrade() -> None:
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_mime_type", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_file_name", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_telegram_file_unique_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_telegram_file_id", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "telegram_questions",
        sa.Column("attachment_kind", sa.String(length=32), nullable=True),
    )

    op.execute(
        """
        UPDATE telegram_questions AS q
        SET attachment_kind = a.kind,
            attachment_telegram_file_id = a.telegram_file_id,
            attachment_telegram_file_unique_id = a.telegram_file_unique_id,
            attachment_file_name = a.file_name,
            attachment_mime_type = a.mime_type,
            attachment_file_size = a.file_size
        FROM (
            SELECT DISTINCT ON (question_id) *
            FROM telegram_question_attachments
            WHERE source = 'student'
            ORDER BY question_id, created_at ASC
        ) AS a
        WHERE a.question_id = q.id
        """
    )

    op.drop_index(
        "ix_telegram_question_attachments_telegram_file_unique_id",
        table_name="telegram_question_attachments",
    )
    op.drop_index(
        "ix_telegram_question_attachments_source", table_name="telegram_question_attachments"
    )
    op.drop_index(
        "ix_telegram_question_attachments_question_id", table_name="telegram_question_attachments"
    )
    op.drop_table("telegram_question_attachments")
