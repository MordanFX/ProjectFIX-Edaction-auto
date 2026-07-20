"""allow curators to answer Telegram questions from the bot

Revision ID: 20260720_02
Revises: 20260720_01
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_02"
down_revision: str | None = "20260720_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_questions", sa.Column("answer_text", sa.Text(), nullable=True)
    )

    op.alter_column(
        "staff_bot_states", "submission_id", existing_type=sa.Uuid(), nullable=True
    )
    op.alter_column(
        "staff_bot_states",
        "verdict",
        existing_type=sa.String(length=18),
        nullable=True,
    )
    op.alter_column(
        "staff_bot_states", "source_chat_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.alter_column(
        "staff_bot_states", "source_message_id", existing_type=sa.Integer(), nullable=True
    )
    op.add_column(
        "staff_bot_states", sa.Column("question_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_staff_bot_states_question_id_telegram_questions",
        "staff_bot_states",
        "telegram_questions",
        ["question_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_staff_bot_states_question_id", "staff_bot_states", ["question_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_staff_bot_states_question_id", table_name="staff_bot_states")
    op.drop_constraint(
        "fk_staff_bot_states_question_id_telegram_questions",
        "staff_bot_states",
        type_="foreignkey",
    )
    op.drop_column("staff_bot_states", "question_id")
    op.alter_column(
        "staff_bot_states", "source_message_id", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "staff_bot_states", "source_chat_id", existing_type=sa.BigInteger(), nullable=False
    )
    op.alter_column(
        "staff_bot_states",
        "verdict",
        existing_type=sa.String(length=18),
        nullable=False,
    )
    op.alter_column(
        "staff_bot_states", "submission_id", existing_type=sa.Uuid(), nullable=False
    )
    op.drop_column("telegram_questions", "answer_text")
