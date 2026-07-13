"""split Telegram and Discord student streams

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3d4e5f6a7b8c"
down_revision: str | None = "2c3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.alter_column(
            "telegram_user_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "origin",
                sa.Enum("telegram", "discord", name="student_origin", native_enum=False),
                server_default="telegram",
                nullable=False,
            )
        )
        batch_op.create_index("ix_students_origin", ["origin"], unique=False)

    with op.batch_alter_table("courses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "audience",
                sa.Enum("telegram", "discord", name="course_audience", native_enum=False),
                server_default="telegram",
                nullable=False,
            )
        )
        batch_op.create_index("ix_courses_audience", ["audience"], unique=False)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM students WHERE origin = 'discord'"))
    with op.batch_alter_table("courses") as batch_op:
        batch_op.drop_index("ix_courses_audience")
        batch_op.drop_column("audience")
    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_index("ix_students_origin")
        batch_op.drop_column("origin")
        batch_op.alter_column(
            "telegram_user_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
