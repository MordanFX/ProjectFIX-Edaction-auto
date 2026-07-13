"""add lesson reminder policies and durable queue

Revision ID: b73ac912de40
Revises: e42f0a9c113b
Create Date: 2026-06-30 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b73ac912de40"
down_revision: str | None = "e42f0a9c113b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("timezone", sa.String(length=64), server_default="Europe/Kyiv", nullable=False),
    )
    op.add_column(
        "students",
        sa.Column("quiet_hours_start", sa.Integer(), server_default="22", nullable=False),
    )
    op.add_column(
        "students",
        sa.Column("quiet_hours_end", sa.Integer(), server_default="9", nullable=False),
    )
    op.add_column(
        "students",
        sa.Column("reminders_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "students",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default="1970-01-01 00:00:00",
            nullable=False,
        ),
    )
    op.execute("UPDATE students SET last_activity_at = updated_at")

    op.create_table(
        "course_reminder_steps",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("delay_hours", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "student_gentle",
                "student_follow_up",
                "curator_alert",
                name="reminder_kind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.CheckConstraint("delay_hours >= 0", name="non_negative_reminder_delay"),
        sa.CheckConstraint("sequence > 0", name="positive_reminder_sequence"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_course_reminder_steps_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_reminder_steps")),
        sa.UniqueConstraint("course_id", "sequence", name="course_reminder_sequence"),
    )
    op.create_index(
        op.f("ix_course_reminder_steps_course_id"),
        "course_reminder_steps",
        ["course_id"],
        unique=False,
    )

    op.create_table(
        "lesson_reminders",
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "failed",
                "cancelled",
                name="reminder_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            name=op.f("fk_lesson_reminders_enrollment_id_enrollments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_reminders_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["course_reminder_steps.id"],
            name=op.f("fk_lesson_reminders_step_id_course_reminder_steps"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_reminders")),
        sa.UniqueConstraint("enrollment_id", "lesson_id", "step_id", name="lesson_reminder_step"),
    )
    for column in ("enrollment_id", "lesson_id", "step_id", "status", "scheduled_at"):
        op.create_index(
            op.f(f"ix_lesson_reminders_{column}"),
            "lesson_reminders",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("scheduled_at", "status", "step_id", "lesson_id", "enrollment_id"):
        op.drop_index(op.f(f"ix_lesson_reminders_{column}"), table_name="lesson_reminders")
    op.drop_table("lesson_reminders")
    op.drop_index(
        op.f("ix_course_reminder_steps_course_id"),
        table_name="course_reminder_steps",
    )
    op.drop_table("course_reminder_steps")
    op.drop_column("students", "last_activity_at")
    op.drop_column("students", "reminders_enabled")
    op.drop_column("students", "quiet_hours_end")
    op.drop_column("students", "quiet_hours_start")
    op.drop_column("students", "timezone")
