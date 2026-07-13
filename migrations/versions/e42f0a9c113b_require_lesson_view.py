"""require configurable lesson view confirmation

Revision ID: e42f0a9c113b
Revises: 9c21d7b43a10
Create Date: 2026-06-30 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e42f0a9c113b"
down_revision: str | None = "9c21d7b43a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column(
            "requires_view_confirmation",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("lessons", "requires_view_confirmation")
