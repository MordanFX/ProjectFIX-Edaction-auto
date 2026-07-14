"""FastAPI authentication and protected review queue tests."""

from asyncio import to_thread
from pathlib import Path

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.api.app import create_app
from course_platform.api.security import hash_password
from course_platform.config import Settings
from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    DiscordHomeworkSpace,
    Enrollment,
    FeedbackAttachment,
    Lesson,
    LessonMaterial,
    StaffUser,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    CourseAudience,
    EnrollmentStatus,
    StaffRole,
    VideoSource,
)
from course_platform.services.discord_participants import DiscordParticipantService
from course_platform.services.progression import ProgressionService
from course_platform.services.students import StudentRegistration, StudentService
from course_platform.services.submissions import HomeworkAttachment, SubmissionService


def api_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        telegram_bot_token=SecretStr("test-telegram-token"),
        jwt_secret=SecretStr("test-secret-that-is-long-enough-for-hs256-signing"),
        _env_file=None,
    )


async def create_staff(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    login: str = "curator",
    password: str = "correct-password",
    display_name: str = "API Curator",
    telegram_user_id: int | None = None,
    role: StaffRole = StaffRole.CURATOR,
) -> StaffUser:
    async with session_factory() as session:
        staff = StaffUser(
            login=login,
            password_hash=hash_password(password),
            display_name=display_name,
            telegram_user_id=telegram_user_id,
            role=role,
        )
        session.add(staff)
        await session.commit()
        return staff


def build_client(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings | None = None,
    telegram_transport: httpx.AsyncBaseTransport | None = None,
    vimeo_transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    application = create_app(
        settings=settings or api_settings(),
        session_factory=session_factory,
        telegram_transport=telegram_transport,
        vimeo_transport=vimeo_transport,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
    )


async def login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/auth/token",
        data={"username": "curator", "password": "correct-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def test_health_is_public(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with build_client(session_factory) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_discord_overview_requires_auth_and_returns_linked_space(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    participant = await DiscordParticipantService(session_factory).get_or_create(
        guild_id=100,
        discord_user_id=200,
        display_name="Discord Student",
    )
    async with session_factory() as session:
        course = Course(
            slug="discord-api",
            title="Discord course",
            audience=CourseAudience.DISCORD,
        )
        cohort = Cohort(title="Discord cohort")
        course.cohorts.append(cohort)
        session.add(
            DiscordHomeworkSpace(
                guild_id=100,
                discord_user_id=200,
                student_id=participant.student_id,
                parent_channel_id=300,
                channel_id=400,
                kind="private_thread",
                display_name="Discord Student",
            )
        )
        session.add_all(
            [course, Enrollment(student_id=participant.student_id, cohort=cohort)]
        )
        await session.commit()

    async with build_client(session_factory) as client:
        unauthorized = await client.get("/api/discord/overview")
        token = await login(client)
        response = await client.get(
            "/api/discord/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        telegram_summary = await client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with session_factory() as session:
            enrollment = await session.scalar(select(Enrollment))
            assert enrollment is not None
            enrollment.status = EnrollmentStatus.COMPLETED
            await session.commit()
        completed_response = await client.get(
            "/api/discord/overview",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["participants"] == 1
    assert payload["active_students"] == 1
    assert payload["private_spaces"] == 1
    assert payload["submissions_enabled"] is False
    assert payload["members"][0]["student_name"] == "Discord Student"
    assert payload["members"][0]["course_title"] == "Discord course"
    assert payload["members"][0]["channel_id"] == "400"
    assert payload["members"][0]["status"] == "active"
    assert telegram_summary.status_code == 200
    assert telegram_summary.json()["active_students"] == 0
    assert completed_response.status_code == 200
    completed_payload = completed_response.json()
    assert completed_payload["active_students"] == 0
    assert completed_payload["members"][0]["status"] == "completed"


async def test_login_and_current_staff(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    staff = await create_staff(session_factory)

    async with build_client(session_factory) as client:
        wrong_password = await client.post(
            "/api/auth/token",
            data={"username": "curator", "password": "wrong"},
        )
        token = await login(client)
        current_staff = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert wrong_password.status_code == 401
    assert current_staff.status_code == 200
    assert current_staff.json() == {
        "id": str(staff.id),
        "login": "curator",
        "display_name": "API Curator",
        "role": "curator",
    }


async def test_staff_management_requires_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    async with build_client(session_factory) as client:
        token = await login(client)
        response = await client.get(
            "/api/staff",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


async def test_admin_can_create_staff_member(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory, role=StaffRole.ADMIN)
    async with build_client(session_factory) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/staff",
            headers=auth,
            json={
                "login": "vlad",
                "password": "strong-password",
                "display_name": "Влад Стрельников",
                "role": "curator",
                "telegram_user_id": 987654321,
                "is_active": True,
            },
        )
        staff_list = await client.get("/api/staff", headers=auth)

    assert created.status_code == 201
    payload = created.json()
    assert payload["login"] == "vlad"
    assert payload["display_name"] == "Влад Стрельников"
    assert payload["role"] == "curator"
    assert payload["telegram_user_id"] == 987654321
    assert payload["is_active"] is True
    assert {item["login"] for item in staff_list.json()} == {"curator", "vlad"}


async def test_admin_can_update_staff_member(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory, role=StaffRole.ADMIN)
    staff = await create_staff(
        session_factory,
        login="vlad",
        password="old-password",
        role=StaffRole.CURATOR,
    )

    async with build_client(session_factory) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        updated = await client.patch(
            f"/api/staff/{staff.id}",
            headers=auth,
            json={
                "password": "new-password",
                "display_name": "Vlad Updated",
                "role": "admin",
                "telegram_user_id": 123456789,
                "is_active": True,
            },
        )
        login_response = await client.post(
            "/api/auth/token",
            data={"username": "vlad", "password": "new-password"},
        )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["display_name"] == "Vlad Updated"
    assert payload["role"] == "admin"
    assert payload["telegram_user_id"] == 123456789
    assert payload["pending_assigned"] == 0
    assert payload["reviewed_total"] == 0
    assert login_response.status_code == 200


async def test_staff_linked_telegram_user_is_hidden_from_students(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(
        session_factory,
        role=StaffRole.ADMIN,
        telegram_user_id=111,
    )
    await StudentService(session_factory).register(
        StudentRegistration(
            telegram_user_id=111,
            first_name="Doc",
            username="fking_01",
        )
    )
    async with build_client(session_factory) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        students = await client.get("/api/students", headers=auth)
        summary = await client.get("/api/dashboard/summary", headers=auth)

    assert students.status_code == 200
    assert students.json() == []
    assert summary.json()["active_students"] == 0


async def test_lesson_cover_requires_auth_and_returns_image_or_vimeo_cover(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    async with session_factory() as session:
        course = Course(slug="covers", title="Cover course")
        image_lesson = Lesson(
            course=course,
            position=1,
            title="Image lesson",
            video_source=VideoSource.PLACEHOLDER,
        )
        image_lesson.materials.append(
            LessonMaterial(
                position=1,
                title="Cover",
                kind="image",
                video_reference="frontend/public/covers/image-lesson.png",
            )
        )
        vimeo_lesson = Lesson(
            course=course,
            position=2,
            title="Vimeo lesson",
            video_source=VideoSource.EXTERNAL_URL,
            video_reference="https://vimeo.com/1196958528",
        )
        session.add_all([course, image_lesson, vimeo_lesson])
        await session.commit()
        image_lesson_id = image_lesson.id
        vimeo_lesson_id = vimeo_lesson.id

    async def vimeo_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/oembed.json"
        assert request.url.params["url"] == "https://vimeo.com/1196958528"
        return httpx.Response(
            200,
            json={"thumbnail_url": "https://i.vimeocdn.com/video/lesson.jpg"},
        )

    async with build_client(
        session_factory,
        vimeo_transport=httpx.MockTransport(vimeo_handler),
    ) as client:
        unauthorized = await client.get(f"/api/courses/lessons/{image_lesson_id}/cover")
        token = await login(client)
        image_response = await client.get(
            f"/api/courses/lessons/{image_lesson_id}/cover",
            headers={"Authorization": f"Bearer {token}"},
        )
        vimeo_response = await client.get(
            f"/api/courses/lessons/{vimeo_lesson_id}/cover",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert unauthorized.status_code == 401
    assert image_response.status_code == 200
    assert image_response.json() == {
        "cover_url": "/covers/image-lesson.png",
        "source": "image",
    }
    assert vimeo_response.status_code == 200
    assert vimeo_response.json() == {
        "cover_url": "https://i.vimeocdn.com/video/lesson.jpg",
        "source": "vimeo",
    }


async def test_copy_lesson_from_knowledge_creates_independent_course_lesson(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    async with session_factory() as session:
        source_course = Course(slug="source-knowledge", title="Source")
        target_course = Course(
            slug="target-discord",
            title="Target",
            audience=CourseAudience.DISCORD,
        )
        source_lesson = Lesson(
            course=source_course,
            position=1,
            title="Risk management",
            description="Base lesson",
            video_source=VideoSource.EXTERNAL_URL,
            video_reference="https://vimeo.com/1196958528",
            is_published=True,
        )
        source_lesson.assignment = Assignment(
            instructions="Send risk plan",
            is_required=True,
        )
        source_lesson.materials.append(
            LessonMaterial(
                position=1,
                title="Chart",
                kind="image",
                video_reference="frontend/public/charts/risk.png",
            )
        )
        session.add_all([source_course, target_course, source_lesson])
        await session.commit()
        source_lesson_id = source_lesson.id
        target_course_id = target_course.id

    async with build_client(session_factory) as client:
        token = await login(client)
        response = await client.post(
            f"/api/courses/{target_course_id}/lessons/from-knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json={"source_lesson_id": str(source_lesson_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["course_id"] == str(target_course_id)
    assert len(payload["lessons"]) == 1
    copied = payload["lessons"][0]
    assert copied["lesson_id"] != str(source_lesson_id)
    assert copied["title"] == "Risk management"
    assert copied["assignment"]["instructions"] == "Send risk plan"
    assert copied["materials"][0]["title"] == "Chart"
    assert copied["is_published"] is True


async def test_review_queue_requires_auth_and_returns_pending_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    await StudentService(session_factory).register(
        StudentRegistration(
            telegram_user_id=111,
            first_name="Demo",
            last_name="Student",
        )
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(111)
    submissions = SubmissionService(session_factory)
    await submissions.begin(111)
    await submissions.submit_text(111, "Homework from API test")

    async with build_client(session_factory) as client:
        unauthorized = await client.get("/api/reviews")
        token = await login(client)
        response = await client.get(
            "/api/reviews",
            headers={"Authorization": f"Bearer {token}"},
        )
        submission_id = response.json()[0]["submission_id"]
        detail = await client.get(
            f"/api/reviews/{submission_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        dashboard = await client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        students = await client.get(
            "/api/students",
            headers={"Authorization": f"Bearer {token}"},
        )
        student_overview = students.json()[0]
        student_detail = await client.get(
            f"/api/students/{student_overview['student_id']}",
            params={"enrollment_id": student_overview["enrollment_id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        lesson_progress = student_detail.json()["lesson_progress"]
        first_lesson_detail = await client.get(
            f"/api/students/{student_overview['student_id']}/lessons/"
            f"{lesson_progress[0]['lesson_id']}",
            params={"enrollment_id": student_overview["enrollment_id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        locked_lesson_detail = await client.get(
            f"/api/students/{student_overview['student_id']}/lessons/"
            f"{lesson_progress[2]['lesson_id']}",
            params={"enrollment_id": student_overview["enrollment_id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        courses = await client.get(
            "/api/courses",
            headers={"Authorization": f"Bearer {token}"},
        )
        course_cohorts = await client.get(
            f"/api/courses/{student_overview['course_id']}/cohorts",
            headers={"Authorization": f"Bearer {token}"},
        )
        created_cohorts = await client.post(
            f"/api/courses/{student_overview['course_id']}/cohorts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "New cohort", "is_active": True},
        )
        updated_cohorts = await client.patch(
            f"/api/courses/{student_overview['course_id']}/cohorts/{course_cohorts.json()[0]['cohort_id']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "Edited cohort", "is_active": False},
        )
        updated_access = await client.patch(
            f"/api/students/{student_overview['student_id']}/access",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "cohort_id": student_overview["cohort_id"],
                "status": "paused",
                "access_type": "trial",
                "current_lesson_position": 2,
            },
        )
        decision = await client.post(
            f"/api/reviews/{submission_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "verdict": "accepted",
                "message": "Accepted from the API",
            },
        )
        duplicate_decision = await client.post(
            f"/api/reviews/{submission_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"verdict": "accepted", "message": "Again"},
        )
        empty_queue = await client.get(
            "/api/reviews",
            headers={"Authorization": f"Bearer {token}"},
        )
        reviewed_detail = await client.get(
            f"/api/reviews/{submission_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    queue = response.json()
    assert len(queue) == 1
    assert queue[0]["student_name"] == "Demo Student"
    assert queue[0]["lesson_position"] == 1
    assert queue[0]["text_body"] == "Homework from API test"
    assert queue[0]["status"] == "submitted"
    assert detail.status_code == 200
    assert detail.json()["attachments"] == []
    assert detail.json()["text_body"] == "Homework from API test"
    assert dashboard.status_code == 200
    assert dashboard.json()["pending_reviews"] == 1
    assert dashboard.json()["active_students"] == 1
    assert students.status_code == 200
    assert students.json()[0]["course_title"] == "Демонстрационный учебный курс"
    assert students.json()[0]["total_lessons"] == 3
    assert student_detail.status_code == 200
    assert student_detail.json()["telegram_user_id"] == 111
    assert student_detail.json()["total_attempts"] == 1
    assert student_detail.json()["pending_submissions"] == 1
    assert student_detail.json()["timezone"] == "Europe/Kyiv"
    assert student_detail.json()["reminders_enabled"] is True
    assert student_detail.json()["next_reminder_at"] is None
    assert student_detail.json()["lesson_progress"][0]["status"] == "homework_submitted"
    assert student_detail.json()["recent_submissions"][0]["lesson_title"] == (
        "Знакомство с курсом"
    )
    assert first_lesson_detail.status_code == 200
    assert first_lesson_detail.json()["assignment_instructions"]
    assert first_lesson_detail.json()["attempts"][0]["text_body"] == (
        "Homework from API test"
    )
    assert locked_lesson_detail.status_code == 200
    assert locked_lesson_detail.json()["status"] == "locked"
    assert locked_lesson_detail.json()["attempts"] == []
    assert courses.status_code == 200
    assert courses.json()[0]["lessons_count"] == 3
    assert courses.json()[0]["students_count"] == 1
    assert course_cohorts.status_code == 200
    assert course_cohorts.json()[0]["students_count"] == 1
    assert created_cohorts.status_code == 200
    assert any(item["title"] == "New cohort" for item in created_cohorts.json())
    assert updated_cohorts.status_code == 200
    edited_cohort = next(
        item for item in updated_cohorts.json() if item["title"] == "Edited cohort"
    )
    assert edited_cohort["is_active"] is False
    assert updated_access.status_code == 200
    assert updated_access.json()["enrollment_status"] == "paused"
    assert updated_access.json()["access_type"] == "trial"
    assert updated_access.json()["current_lesson_position"] == 2
    assert decision.status_code == 200
    assert decision.json()["verdict"] == "accepted"
    assert decision.json()["current_lesson_position"] == 2
    assert duplicate_decision.status_code == 409
    assert len(empty_queue.json()) == 1
    assert empty_queue.json()[0]["submission_id"] == submission_id
    assert empty_queue.json()[0]["status"] == "accepted"
    assert reviewed_detail.status_code == 200
    assert reviewed_detail.json()["feedback_verdict"] == "accepted"
    assert reviewed_detail.json()["feedback_message"] == "Accepted from the API"
    assert reviewed_detail.json()["reviewed_at"] is not None
    assert reviewed_detail.json()["reviewer_name"] == "API Curator"


async def test_review_decision_can_upload_curator_attachment(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await create_staff(session_factory)
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=111, first_name="Demo")
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(111)
    submissions = SubmissionService(session_factory)
    await submissions.begin(111)
    await submissions.submit_text(111, "Need markup")

    settings = api_settings()
    settings.feedback_upload_dir = str(tmp_path)

    async with build_client(session_factory, settings=settings) as client:
        token = await login(client)
        queue = await client.get(
            "/api/reviews",
            headers={"Authorization": f"Bearer {token}"},
        )
        submission_id = queue.json()[0]["submission_id"]
        decision = await client.post(
            f"/api/reviews/{submission_id}/decision-with-attachment",
            headers={"Authorization": f"Bearer {token}"},
            data={"verdict": "revision_requested", "message": ""},
            files={"attachment": ("markup.png", b"fake-image", "image/png")},
        )
        detail = await client.get(
            f"/api/reviews/{submission_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    async with session_factory() as session:
        feedback_attachment = await session.scalar(select(FeedbackAttachment))

    assert decision.status_code == 200
    assert decision.json()["verdict"] == "revision_requested"
    assert feedback_attachment is not None
    assert feedback_attachment.file_name == "markup.png"
    assert feedback_attachment.local_path is not None
    assert await to_thread(Path(feedback_attachment.local_path).is_file)
    assert detail.status_code == 200
    assert detail.json()["feedback_message"] == "См. вложение куратора."
    assert detail.json()["feedback_attachments"][0]["file_name"] == "markup.png"


async def test_review_assignment_and_curator_stats(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory, login="curator", password="correct-password")
    await create_staff(
        session_factory,
        login="other",
        password="correct-password",
        display_name="Other Curator",
    )
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=111, first_name="Demo")
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(111)
    submissions = SubmissionService(session_factory)
    await submissions.begin(111)
    await submissions.submit_text(111, "Work to assign")

    async with build_client(session_factory) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        queue = await client.get("/api/reviews", headers=auth)
        submission_id = queue.json()[0]["submission_id"]
        assigned = await client.post(f"/api/reviews/{submission_id}/assign", headers=auth)
        stats_after_assign = await client.get("/api/reviews/me/stats", headers=auth)
        released = await client.post(f"/api/reviews/{submission_id}/release", headers=auth)
        assigned_again = await client.post(f"/api/reviews/{submission_id}/assign", headers=auth)
        decision = await client.post(
            f"/api/reviews/{submission_id}/decision",
            headers=auth,
            json={"verdict": "accepted", "message": "Done"},
        )
        stats_after_review = await client.get("/api/reviews/me/stats", headers=auth)

    assert assigned.status_code == 200
    assert assigned.json()["status"] == "in_review"
    assert assigned.json()["assigned_reviewer_name"] == "API Curator"
    assert stats_after_assign.json()["pending_assigned"] == 1
    assert released.status_code == 200
    assert released.json()["status"] == "submitted"
    assert released.json()["assigned_reviewer_id"] is None
    assert assigned_again.status_code == 200
    assert decision.status_code == 200
    assert stats_after_review.json()["pending_assigned"] == 0
    assert stats_after_review.json()["reviewed_total"] == 1
    assert stats_after_review.json()["accepted_total"] == 1


async def test_video_playback_uses_protected_range_proxy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=333, first_name="Video", last_name="Student")
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(333)
    submissions = SubmissionService(session_factory)
    await submissions.begin(333)
    await submissions.submit_attachment(
        333,
        HomeworkAttachment(
            kind=AttachmentKind.VIDEO,
            telegram_file_id="telegram-video-id",
            telegram_file_unique_id="stable-video-id",
            file_name="homework.mp4",
            mime_type="video/mp4",
            file_size=8,
            source_chat_id=333,
            source_message_id=10,
        ),
    )

    async with session_factory() as session:
        attachment = await session.scalar(select(SubmissionAttachment))
    assert attachment is not None

    async def telegram_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "file_id": "telegram-video-id",
                        "file_unique_id": "stable-video-id",
                        "file_size": 8,
                        "file_path": "videos/homework.mp4",
                    },
                },
            )
        assert request.url.path.endswith(
            "/file/bottest-telegram-token/videos/homework.mp4"
        )
        assert request.headers["range"] == "bytes=0-3"
        return httpx.Response(
            206,
            content=b"test",
            headers={
                "content-type": "video/mp4",
                "content-length": "4",
                "content-range": "bytes 0-3/8",
                "accept-ranges": "bytes",
            },
        )

    transport = httpx.MockTransport(telegram_handler)
    async with build_client(session_factory, telegram_transport=transport) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        playback = await client.post(
            f"/api/reviews/{attachment.submission_id}/attachments/{attachment.id}/playback",
            headers=auth,
        )
        unauthorized_playback = await client.post(
            f"/api/reviews/{attachment.submission_id}/attachments/{attachment.id}/playback"
        )
        media = await client.get(
            playback.json()["url"],
            headers={"Range": "bytes=0-3"},
        )

    assert playback.status_code == 200
    assert playback.json()["expires_in"] == 1800
    assert unauthorized_playback.status_code == 401
    assert media.status_code == 206
    assert media.headers["content-type"] == "video/mp4"
    assert media.headers["content-range"] == "bytes 0-3/8"
    assert media.content == b"test"


async def test_course_content_can_be_edited_and_extended(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_staff(session_factory)
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=444, first_name="Course", last_name="Editor")
    )
    await seed_demo_data(session_factory)

    async with build_client(session_factory) as client:
        token = await login(client)
        auth = {"Authorization": f"Bearer {token}"}
        overview = await client.get("/api/courses", headers=auth)
        course_id = overview.json()[0]["course_id"]
        detail = await client.get(f"/api/courses/{course_id}", headers=auth)
        analytics = await client.get(f"/api/courses/{course_id}/analytics", headers=auth)
        updated_course = await client.patch(
            f"/api/courses/{course_id}",
            headers=auth,
            json={
                "title": "Обновлённый курс",
                "description": "Описание из конструктора",
                "is_active": True,
            },
        )
        first_lesson = detail.json()["lessons"][0]
        lesson_payload = {
            "title": "Обновлённый первый урок",
            "description": "Материал урока",
            "video_source": "external_url",
            "video_reference": "https://example.com/lesson",
            "release_offset_hours": 0,
            "requires_view_confirmation": True,
            "is_published": True,
            "assignment": {
                "instructions": "Выполните практическую работу",
                "submission_kind": "any",
                "is_required": True,
            },
        }
        updated_lesson = await client.patch(
            f"/api/courses/{course_id}/lessons/{first_lesson['lesson_id']}",
            headers=auth,
            json=lesson_payload,
        )
        created_lesson = await client.post(
            f"/api/courses/{course_id}/lessons",
            headers=auth,
            json={
                **lesson_payload,
                "title": "Новый урок",
                "is_published": False,
            },
        )
        created_course = await client.post(
            "/api/courses",
            headers=auth,
            json={
                "title": "Новая программа",
                "description": "Создана через конструктор",
                "is_active": True,
            },
        )
        updated_reminders = await client.put(
            f"/api/courses/{course_id}/reminder-steps",
            headers=auth,
            json={
                "steps": [
                    {
                        "delay_hours": 12,
                        "kind": "student_gentle",
                        "message_text": "Вернитесь к уроку {lesson_title}",
                        "is_active": True,
                    },
                    {
                        "delay_hours": 48,
                        "kind": "curator_alert",
                        "message_text": "Нужна помощь куратора",
                        "is_active": True,
                    },
                ]
            },
        )

    assert detail.status_code == 200
    assert len(detail.json()["lessons"]) == 3
    assert analytics.status_code == 200
    assert analytics.json()["total_students"] == 1
    assert analytics.json()["cohorts"][0]["lesson_stages"][0]["students_count"] == 1
    assert updated_course.status_code == 200
    assert updated_course.json()["title"] == "Обновлённый курс"
    assert updated_lesson.status_code == 200
    assert updated_lesson.json()["lessons"][0]["video_source"] == "external_url"
    assert created_lesson.status_code == 200
    assert created_lesson.json()["lessons"][-1]["position"] == 4
    assert created_course.status_code == 200
    assert created_course.json()["title"] == "Новая программа"
    assert created_course.json()["lessons"] == []
    assert created_lesson.json()["lessons"][-1]["is_published"] is False
    assert updated_reminders.status_code == 200
    assert [step["delay_hours"] for step in updated_reminders.json()["reminder_steps"]] == [
        12,
        48,
    ]
    assert updated_reminders.json()["reminder_steps"][1]["kind"] == "curator_alert"
