"""add per-material viewing progress

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lesson_material_progress",
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("material_id", sa.Uuid(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["material_id"], ["lesson_materials.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "enrollment_id", "material_id", name="uq_lesson_material_progress_enrollment_material"
        ),
    )
    op.create_index(
        op.f("ix_lesson_material_progress_enrollment_id"),
        "lesson_material_progress",
        ["enrollment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_material_progress_material_id"),
        "lesson_material_progress",
        ["material_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_lesson_material_progress_material_id"),
        table_name="lesson_material_progress",
    )
    op.drop_index(
        op.f("ix_lesson_material_progress_enrollment_id"),
        table_name="lesson_material_progress",
    )
    op.drop_table("lesson_material_progress")
