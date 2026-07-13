"""enrich Discord participants and migrate legacy spaces

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-07-07
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "4e5f6a7b8c9d"
down_revision: str | None = "3d4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("discord_student_links")
    }
    with op.batch_alter_table("discord_student_links") as batch_op:
        if "display_name" not in columns:
            batch_op.add_column(
                sa.Column("display_name", sa.String(length=100), nullable=True)
            )
        if "avatar_hash" not in columns:
            batch_op.add_column(
                sa.Column("avatar_hash", sa.String(length=128), nullable=True)
            )

    metadata = sa.MetaData()
    students = sa.Table("students", metadata, autoload_with=bind)
    participants = sa.Table("discord_student_links", metadata, autoload_with=bind)
    spaces = sa.Table("discord_homework_spaces", metadata, autoload_with=bind)

    existing = {
        (row.guild_id, row.discord_user_id)
        for row in bind.execute(
            sa.select(participants.c.guild_id, participants.c.discord_user_id)
        )
    }
    for space in bind.execute(
        sa.select(
            spaces.c.guild_id,
            spaces.c.discord_user_id,
            spaces.c.display_name,
            spaces.c.id,
        )
    ):
        key = (space.guild_id, space.discord_user_id)
        if key in existing:
            bind.execute(
                participants.update()
                .where(
                    participants.c.guild_id == space.guild_id,
                    participants.c.discord_user_id == space.discord_user_id,
                )
                .values(display_name=space.display_name)
            )
            continue
        student_uuid = uuid4()
        participant_uuid = uuid4()
        student_id = student_uuid.hex if bind.dialect.name == "sqlite" else student_uuid
        participant_id = (
            participant_uuid.hex if bind.dialect.name == "sqlite" else participant_uuid
        )
        bind.execute(
            students.insert().values(
                id=student_id,
                telegram_user_id=None,
                origin="discord",
                first_name=space.display_name,
                is_active=True,
            )
        )
        bind.execute(
            participants.insert().values(
                id=participant_id,
                guild_id=space.guild_id,
                discord_user_id=space.discord_user_id,
                student_id=student_id,
                display_name=space.display_name,
            )
        )
        bind.execute(
            spaces.update().where(spaces.c.id == space.id).values(student_id=student_id)
        )
        existing.add(key)

    bind.execute(
        participants.update()
        .where(participants.c.display_name.is_(None))
        .values(display_name="Discord participant")
    )
    with op.batch_alter_table("discord_student_links") as batch_op:
        batch_op.alter_column(
            "display_name",
            existing_type=sa.String(length=100),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("discord_student_links") as batch_op:
        batch_op.drop_column("avatar_hash")
        batch_op.drop_column("display_name")
