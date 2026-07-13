"""add per-lesson progress and release schedule

Revision ID: 9c21d7b43a10
Revises: 05066ac3b094
Create Date: 2026-06-30 19:30:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "9c21d7b43a10"
down_revision: str | None = "05066ac3b094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("release_offset_hours", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "lesson_progress",
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "locked",
                "available",
                "viewed",
                "homework_submitted",
                "completed",
                name="lesson_progress_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("homework_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["enrollment_id"],
            ["enrollments.id"],
            name=op.f("fk_lesson_progress_enrollment_id_enrollments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_progress_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_progress")),
        sa.UniqueConstraint("enrollment_id", "lesson_id", name="enrollment_lesson"),
    )
    op.create_index(
        op.f("ix_lesson_progress_enrollment_id"),
        "lesson_progress",
        ["enrollment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_progress_lesson_id"),
        "lesson_progress",
        ["lesson_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_progress_release_at"),
        "lesson_progress",
        ["release_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_progress_status"),
        "lesson_progress",
        ["status"],
        unique=False,
    )
    _backfill_progress()


def _backfill_progress() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                e.id AS enrollment_id,
                e.status AS enrollment_status,
                e.current_lesson_position,
                e.created_at AS enrollment_created_at,
                e.updated_at AS enrollment_updated_at,
                l.id AS lesson_id,
                l.position AS lesson_position,
                l.release_offset_hours
            FROM enrollments e
            JOIN cohorts c ON c.id = e.cohort_id
            JOIN lessons l ON l.course_id = c.course_id
            WHERE l.is_published = true
            """
        )
    ).mappings()
    now = datetime.now(UTC)
    progress_rows: list[dict[str, object]] = []
    for row in rows:
        created_at = _as_datetime(row["enrollment_created_at"]) or now
        if created_at.tzinfo is None:
            comparable_now = now.replace(tzinfo=None)
        else:
            comparable_now = now
        release_at = created_at + timedelta(hours=row["release_offset_hours"] or 0)
        is_completed = (
            row["enrollment_status"] == "completed"
            or row["lesson_position"] < row["current_lesson_position"]
        )
        is_available = (
            row["lesson_position"] == row["current_lesson_position"]
            and release_at <= comparable_now
        )
        status = "completed" if is_completed else "available" if is_available else "locked"
        progress_rows.append(
            {
                "id": uuid4(),
                "enrollment_id": _as_uuid(row["enrollment_id"]),
                "lesson_id": _as_uuid(row["lesson_id"]),
                "status": status,
                "release_at": release_at,
                "available_at": (
                    created_at if is_completed else comparable_now if is_available else None
                ),
                "viewed_at": None,
                "homework_submitted_at": None,
                "completed_at": (
                    _as_datetime(row["enrollment_updated_at"]) if is_completed else None
                ),
            }
        )

    if progress_rows:
        progress_table = sa.table(
            "lesson_progress",
            sa.column("id", sa.Uuid()),
            sa.column("enrollment_id", sa.Uuid()),
            sa.column("lesson_id", sa.Uuid()),
            sa.column("status", sa.String()),
            sa.column("release_at", sa.DateTime(timezone=True)),
            sa.column("available_at", sa.DateTime(timezone=True)),
            sa.column("viewed_at", sa.DateTime(timezone=True)),
            sa.column("homework_submitted_at", sa.DateTime(timezone=True)),
            sa.column("completed_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(progress_table, progress_rows)


def _as_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {type(value).__name__}")


def _as_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def downgrade() -> None:
    op.drop_index(op.f("ix_lesson_progress_status"), table_name="lesson_progress")
    op.drop_index(op.f("ix_lesson_progress_release_at"), table_name="lesson_progress")
    op.drop_index(op.f("ix_lesson_progress_lesson_id"), table_name="lesson_progress")
    op.drop_index(op.f("ix_lesson_progress_enrollment_id"), table_name="lesson_progress")
    op.drop_table("lesson_progress")
    op.drop_column("lessons", "release_offset_hours")
