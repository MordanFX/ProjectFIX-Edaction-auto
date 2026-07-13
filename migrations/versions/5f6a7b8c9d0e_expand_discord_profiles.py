"""expand Discord participant profiles and homework space metadata

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f6a7b8c9d0e"
down_revision: str | None = "4e5f6a7b8c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discord_student_links") as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("global_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("guild_joined_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "is_guild_member",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("left_at", sa.DateTime(timezone=True), nullable=True))

    links = sa.table(
        "discord_student_links",
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("last_activity_at", sa.DateTime(timezone=True)),
    )
    op.execute(links.update().values(last_activity_at=links.c.created_at))
    with op.batch_alter_table("discord_student_links") as batch_op:
        batch_op.alter_column(
            "last_activity_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    with op.batch_alter_table("discord_homework_spaces") as batch_op:
        batch_op.add_column(sa.Column("channel_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("discord_homework_spaces") as batch_op:
        batch_op.drop_column("channel_name")
    with op.batch_alter_table("discord_student_links") as batch_op:
        batch_op.drop_column("left_at")
        batch_op.drop_column("is_guild_member")
        batch_op.drop_column("last_activity_at")
        batch_op.drop_column("guild_joined_at")
        batch_op.drop_column("global_name")
        batch_op.drop_column("username")
