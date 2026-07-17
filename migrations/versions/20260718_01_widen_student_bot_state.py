"""widen student bot state column

Revision ID: 20260718_01
Revises: 20260716_01
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_01"
down_revision: str | None = "20260716_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The column was sized for the original two states; "awaiting_curator_question"
    # (25 chars) no longer fits into VARCHAR(17) and crashed the question flow.
    op.alter_column(
        "student_bot_states",
        "state",
        existing_type=sa.String(length=17),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE student_bot_states SET state = 'idle' WHERE length(state) > 17"
    )
    op.alter_column(
        "student_bot_states",
        "state",
        existing_type=sa.String(length=32),
        type_=sa.String(length=17),
        existing_nullable=False,
    )
