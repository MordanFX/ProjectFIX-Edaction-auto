"""pin a Telegram student to a single curator

Revision ID: 20260720_03
Revises: 20260720_02
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_03"
down_revision: str | None = "20260720_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "students", sa.Column("assigned_curator_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_students_assigned_curator_id_staff_users",
        "students",
        "staff_users",
        ["assigned_curator_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_students_assigned_curator_id", "students", ["assigned_curator_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_students_assigned_curator_id", table_name="students")
    op.drop_constraint(
        "fk_students_assigned_curator_id_staff_users", "students", type_="foreignkey"
    )
    op.drop_column("students", "assigned_curator_id")
