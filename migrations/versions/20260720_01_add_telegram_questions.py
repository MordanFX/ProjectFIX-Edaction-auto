"""add Telegram student questions

Revision ID: 20260720_01
Revises: 20260718_01
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_01"
down_revision: str | None = "20260718_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_questions",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("attachment_kind", sa.String(length=32), nullable=True),
        sa.Column("attachment_telegram_file_id", sa.String(length=512), nullable=True),
        sa.Column("attachment_telegram_file_unique_id", sa.String(length=255), nullable=True),
        sa.Column("attachment_file_name", sa.String(length=512), nullable=True),
        sa.Column("attachment_mime_type", sa.String(length=255), nullable=True),
        sa.Column("attachment_file_size", sa.BigInteger(), nullable=True),
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
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_questions_student_id", "telegram_questions", ["student_id"])
    op.create_index(
        "ix_telegram_questions_assignment_id", "telegram_questions", ["assignment_id"]
    )
    op.create_index("ix_telegram_questions_status", "telegram_questions", ["status"])
    op.create_index(
        "ix_telegram_questions_resolved_by_staff_id",
        "telegram_questions",
        ["resolved_by_staff_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_questions_resolved_by_staff_id", table_name="telegram_questions")
    op.drop_index("ix_telegram_questions_status", table_name="telegram_questions")
    op.drop_index("ix_telegram_questions_assignment_id", table_name="telegram_questions")
    op.drop_index("ix_telegram_questions_student_id", table_name="telegram_questions")
    op.drop_table("telegram_questions")
