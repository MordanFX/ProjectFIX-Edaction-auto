"""add discord invite access codes

Revision ID: 20260716_01
Revises: 20260715_01
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_01"
down_revision: str | None = "20260715_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Invites issued before the access code carry no code and cannot be redeemed
    # under the gated scheme, so they are dropped rather than given a fake digest.
    op.execute("DELETE FROM discord_invites")
    op.add_column(
        "discord_invites",
        sa.Column("access_code_digest", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "discord_invites",
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discord_invites",
        sa.Column("used_by_discord_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f("ix_discord_invites_access_code_digest"),
        "discord_invites",
        ["access_code_digest"],
    )
    op.create_unique_constraint(
        "discord_invite_access_code",
        "discord_invites",
        ["access_code_digest"],
    )
    op.create_index(
        op.f("ix_discord_invites_used_by_discord_user_id"),
        "discord_invites",
        ["used_by_discord_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_discord_invites_used_by_discord_user_id"),
        table_name="discord_invites",
    )
    op.drop_constraint(
        "discord_invite_access_code", "discord_invites", type_="unique"
    )
    op.drop_index(
        op.f("ix_discord_invites_access_code_digest"), table_name="discord_invites"
    )
    op.drop_column("discord_invites", "used_by_discord_user_id")
    op.drop_column("discord_invites", "used_at")
    op.drop_column("discord_invites", "access_code_digest")
