"""add ordered lesson materials

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lesson_materials",
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "video_source",
            sa.Enum(
                "placeholder",
                "telegram_channel",
                "external_url",
                name="video_source",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("video_reference", sa.Text(), nullable=True),
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
        sa.CheckConstraint("position > 0", name="ck_lesson_materials_positive_material_position"),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lesson_id", "position", name="uq_lesson_materials_lesson_material_position"
        ),
    )
    op.create_index(
        op.f("ix_lesson_materials_lesson_id"),
        "lesson_materials",
        ["lesson_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lesson_materials_lesson_id"), table_name="lesson_materials")
    op.drop_table("lesson_materials")
