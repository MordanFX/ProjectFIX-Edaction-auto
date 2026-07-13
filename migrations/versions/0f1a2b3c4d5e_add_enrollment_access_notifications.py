"""add enrollment access notification marker

Revision ID: 0f1a2b3c4d5e
Revises: 8c9d0e1f2a3b
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f1a2b3c4d5e"
down_revision: str | None = "8c9d0e1f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("enrollments") as batch_op:
        batch_op.add_column(
            sa.Column("access_notified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_enrollments_access_notified_at"),
            ["access_notified_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch_op:
        batch_op.drop_index(op.f("ix_enrollments_access_notified_at"))
        batch_op.drop_column("access_notified_at")
