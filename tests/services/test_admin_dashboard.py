"""Curator visibility scoping for the Telegram student dashboard."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import StaffUser, Student
from course_platform.models.enums import StaffRole
from course_platform.services.access_scope import StaffScope
from course_platform.services.admin_dashboard import (
    AdminDashboardService,
    CuratorNotFoundError,
    StudentNotFoundError,
)
from course_platform.services.students import StudentRegistration, StudentService


async def prepare_student_and_curators(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[StaffScope, StaffScope, StaffScope, str]:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=321, first_name="Pinned")
    )
    await seed_demo_data(session_factory)

    async with session_factory() as session:
        curator_a = StaffUser(login="curator-a", display_name="Curator A")
        curator_b = StaffUser(login="curator-b", display_name="Curator B")
        admin = StaffUser(login="admin-user", display_name="Admin", role=StaffRole.ADMIN)
        session.add_all([curator_a, curator_b, admin])
        await session.flush()
        student = await session.scalar(select(Student))
        assert student is not None
        student_id = student.id
        student.assigned_curator_id = curator_b.id
        await session.commit()
        scope_a = StaffScope(staff_id=curator_a.id, is_admin=False)
        scope_b = StaffScope(staff_id=curator_b.id, is_admin=False)
        scope_admin = StaffScope(staff_id=admin.id, is_admin=True)

    return scope_a, scope_b, scope_admin, str(student_id)


async def test_pinned_student_only_visible_to_assigned_curator_and_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scope_a, scope_b, scope_admin, student_id = await prepare_student_and_curators(
        session_factory
    )
    dashboard = AdminDashboardService(session_factory)

    students_a = await dashboard.list_students(viewer=scope_a)
    assert students_a == []

    students_b = await dashboard.list_students(viewer=scope_b)
    assert [str(item.student_id) for item in students_b] == [student_id]

    students_admin = await dashboard.list_students(viewer=scope_admin)
    assert [str(item.student_id) for item in students_admin] == [student_id]

    with pytest.raises(StudentNotFoundError):
        await dashboard.get_student_detail(student_id=students_b[0].student_id, viewer=scope_a)

    detail_b = await dashboard.get_student_detail(
        student_id=students_b[0].student_id, viewer=scope_b
    )
    assert detail_b.assigned_curator_name == "Curator B"


async def test_admin_can_assign_and_unassign_curator(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=654, first_name="Loose")
    )
    await seed_demo_data(session_factory)
    dashboard = AdminDashboardService(session_factory)

    async with session_factory() as session:
        curator = StaffUser(login="curator-c", display_name="Curator C")
        session.add(curator)
        await session.commit()
        curator_id = curator.id
        student = await session.scalar(select(Student))
        assert student is not None
        student_id = student.id

    with pytest.raises(CuratorNotFoundError):
        await dashboard.assign_curator(student_id=student_id, curator_id=uuid4())

    detail = await dashboard.assign_curator(student_id=student_id, curator_id=curator_id)
    assert detail.assigned_curator_id == curator_id
    assert detail.assigned_curator_name == "Curator C"

    unassigned = await dashboard.assign_curator(student_id=student_id, curator_id=None)
    assert unassigned.assigned_curator_id is None
