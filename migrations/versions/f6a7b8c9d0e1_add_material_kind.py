"""add lesson material kind

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lesson_materials",
        sa.Column("kind", sa.String(length=32), server_default="video", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("lesson_materials", "kind")
