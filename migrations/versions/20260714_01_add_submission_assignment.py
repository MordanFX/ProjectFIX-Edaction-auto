"""add submission review assignment

Revision ID: 20260714_01
Revises: f6a7b8c9d0e1
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_01"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("assigned_reviewer_id", sa.Uuid(), nullable=True))
    op.add_column(
        "submissions",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_submissions_assigned_reviewer_id"),
        "submissions",
        ["assigned_reviewer_id"],
        unique=False,
    )
    op.create_foreign_key(
        "submission_assigned_reviewer",
        "submissions",
        "staff_users",
        ["assigned_reviewer_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("submission_assigned_reviewer", "submissions", type_="foreignkey")
    op.drop_index(op.f("ix_submissions_assigned_reviewer_id"), table_name="submissions")
    op.drop_column("submissions", "assigned_at")
    op.drop_column("submissions", "assigned_reviewer_id")
