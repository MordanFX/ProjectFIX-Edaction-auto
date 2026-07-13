"""add enrollment access period metadata

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c9d0e1f2a3b"
down_revision: str | None = "7b8c9d0e1f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("enrollments") as batch_op:
        batch_op.add_column(
            sa.Column("access_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("access_source", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("access_plan", sa.String(length=32), nullable=True))
        batch_op.create_index(
            op.f("ix_enrollments_access_expires_at"),
            ["access_expires_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch_op:
        batch_op.drop_index(op.f("ix_enrollments_access_expires_at"))
        batch_op.drop_column("access_plan")
        batch_op.drop_column("access_source")
        batch_op.drop_column("access_expires_at")
        batch_op.drop_column("access_started_at")
