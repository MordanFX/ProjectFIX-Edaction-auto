"""Message command routing for the student-facing bot."""

from html import escape
from pathlib import Path
from uuid import UUID

from course_platform.bot.api import TelegramAPIError, TelegramBotClient, TelegramTransportError
from course_platform.bot.types import (
    TelegramCallbackQuery,
    TelegramMessage,
    TelegramUpdate,
    TelegramUser,
)
from course_platform.bot.ui import curator_keyboard, main_keyboard
from course_platform.integrations.vimeo import VimeoOEmbedClient, vimeo_watch_url
from course_platform.models.enums import (
    AttachmentKind,
    FeedbackVerdict,
    SubmissionKind,
    SubmissionSource,
    SubmissionStatus,
)
from course_platform.services.admin_dashboard import AdminDashboardService
from course_platform.services.learning import CourseOutline, CurrentLesson, LearningService
from course_platform.services.progression import (
    ActiveLessonNotFoundError,
    LessonMismatchError,
    ProgressionResult,
    ProgressionService,
)
from course_platform.services.reviews import (
    EmptyFeedbackError,
    FeedbackAttachmentInput,
    ReviewQueueItem,
    ReviewService,
    SubmissionAlreadyReviewedError,
    SubmissionNotFoundError,
    UnauthorizedReviewerError,
)
from course_platform.services.students import (
    InvalidQuietHoursError,
    InvalidTimezoneError,
    ProgressSnapshot,
    StudentAccessError,
    StudentAccessService,
    StudentJourney,
    StudentRegistration,
    StudentService,
    StudentStage,
)
from course_platform.services.submissions import (
    AssignmentAcceptedError,
    CuratorQuestionReceipt,
    EmptySubmissionError,
    HomeworkAttachment,
    JournalFeedbackAttachment,
    LessonNotViewedError,
    NoActiveAssignmentError,
    NoPendingSubmissionError,
    NotAwaitingQuestionError,
    NotAwaitingSubmissionError,
    SubmissionPendingError,
    SubmissionPrompt,
    SubmissionReceipt,
    SubmissionService,
    SubmissionWorkflowError,
    UnsupportedSubmissionKindError,
)


class MessageRouter:
    """Route supported private-chat commands to application services."""

    def __init__(
        self,
        api: TelegramBotClient,
        students: StudentService,
        learning: LearningService,
        submissions: SubmissionService,
        reviews: ReviewService,
        progression: ProgressionService,
        dashboard: AdminDashboardService,
        access: StudentAccessService | None = None,
        vimeo: VimeoOEmbedClient | None = None,
    ) -> None:
        self._api = api
        self._students = students
        self._learning = learning
        self._submissions = submissions
        self._reviews = reviews
        self._progression = progression
        self._dashboard = dashboard
        self._access = access
        self._vimeo = vimeo
        self._pending_video_lessons: dict[int, UUID] = {}
        self._grant_sessions: dict[int, dict[str, UUID]] = {}
        self._grant_selected_students: dict[int, UUID] = {}

    async def handle(self, update: TelegramUpdate) -> bool:
        if update.callback_query is not None:
            await self._students.touch_activity(update.callback_query.sender.id)
            callback_data = update.callback_query.data or ""
            if callback_data.startswith("matview:"):
                return await self._handle_material_viewed_callback(update)
            if callback_data.startswith("material:"):
                return await self._handle_material_callback(update)
            if callback_data.startswith("homework:"):
                return await self._handle_homework_callback(update)
            if callback_data.startswith("template:"):
                return await self._handle_submission_template_callback(update)
            if callback_data.startswith("submission:"):
                return await self._handle_submission_start_callback(update)
            if callback_data.startswith("ask_curator:"):
                return await self._handle_ask_curator_callback(update)
            if callback_data.startswith("lesson:"):
                return await self._handle_lesson_callback(update)
            if callback_data.startswith("settings:"):
                return await self._handle_settings_callback(update)
            if callback_data.startswith("grant:"):
                return await self._handle_grant_callback(update)
            if callback_data.startswith("course_video:"):
                lesson_id = UUID(callback_data.split(":", 1)[1])
                self._pending_video_lessons[update.callback_query.sender.id] = lesson_id
                await self._api.answer_callback_query(update.callback_query.id, text="Урок выбран")
                if update.callback_query.message:
                    await self._api.send_message(
                        update.callback_query.message.chat.id,
                        "🎬 Теперь отправь видео одним сообщением.",
                        reply_markup=curator_keyboard(),
                    )
                return True
            return await self._handle_review_callback(update)

        message = update.message
        if (
            message is None
            or message.chat.type != "private"
            or message.sender is None
            or message.sender.is_bot
            or (
                not message.text
                and message.document is None
                and not message.photo
                and message.video is None
                and message.video_note is None
            )
        ):
            return False

        await self._students.touch_activity(message.sender.id)

        command = self._extract_command(message.text) if message.text else ""
        pending_feedback = await self._reviews.get_pending_telegram_feedback(message.sender.id)
        reply_markup: dict[str, object] | None = None
        link_preview_options: dict[str, object] | None = None
        lesson_cover_url: str | None = None
        lesson: CurrentLesson | None = None
        pending_video_lesson = self._pending_video_lessons.get(message.sender.id)
        if pending_video_lesson is not None and message.video is not None:
            await self._learning.attach_telegram_video(
                message.sender.id,
                pending_video_lesson,
                message.chat.id,
                message.message_id,
            )
            self._pending_video_lessons.pop(message.sender.id, None)
            response = (
                "✅ <b>Видео привязано к уроку.</b>\n\n"
                "Ученик получит его при открытии урока."
            )
            reply_markup = curator_keyboard()
        elif pending_feedback is not None and command == "/cancel_review":
            await self._reviews.cancel_telegram_feedback(message.sender.id)
            response = (
                "✅ <b>Проверка отменена</b>\n\n"
                "Работа осталась в очереди и доступна для повторного решения."
            )
        elif pending_feedback is not None and not command.startswith("/"):
            response = await self._complete_review_feedback_from_message(
                message.sender.id,
                message,
            )
        elif command == "/start":
            registration = await self._students.register(self._student_registration(message.sender))
            progress = await self._students.get_progress(message.sender.id)
            journey = await self._students.get_journey(message.sender.id)
            greeting = "Привет" if registration.is_new else "С возвращением"
            response = (
                f"👋 <b>{greeting}, {escape(registration.first_name)}!</b>\n\n"
                f"{self._student_dashboard_text(progress, journey)}"
            )
        elif command == "/progress":
            await self._students.register(self._student_registration(message.sender))
            progress = await self._students.get_progress(message.sender.id)
            response = self._progress_text(progress)
        elif command == "/lesson":
            lesson = await self._learning.get_current_lesson(message.sender.id)
            if lesson is None:
                response = self._lesson_unavailable_text(
                    await self._students.get_journey(message.sender.id)
                )
            else:
                response = self._lesson_text(lesson)
            if lesson is not None:
                if lesson.video_source.value == "external_url" and lesson.video_reference:
                    link_preview_options = {
                        "url": vimeo_watch_url(lesson.video_reference),
                        "prefer_large_media": True,
                        "show_above_text": True,
                    }
                    lesson_cover_url = await self._vimeo_thumbnail(lesson.video_reference)
                telegram_source = self._telegram_lesson_source(lesson)
                if telegram_source is not None:
                    source_chat_id, source_message_id = telegram_source
                    try:
                        await self._api.copy_message(
                            message.chat.id,
                            source_chat_id,
                            source_message_id,
                        )
                    except (TelegramAPIError, TelegramTransportError):
                        response += (
                            "\n\n⚠️ Видео временно не удалось загрузить. "
                            "Сообщи куратору, если ошибка повторится."
                        )
            if lesson is not None and lesson.viewed_at is None:
                reply_markup = self._lesson_reply_markup(lesson)
        elif command == "/course":
            response = self._course_outline_text(
                await self._learning.get_course_outline(message.sender.id)
            )
        elif command == "/lessons":
            outline = await self._learning.get_course_outline(message.sender.id)
            response = self._lesson_catalog_text(outline)
            if outline is not None:
                reply_markup = self._lesson_catalog_reply_markup(outline)
        elif command == "/submit":
            response = await self._begin_submission(message.sender.id)
        elif command == "/status":
            response = self._journey_status_text(
                await self._students.get_journey(message.sender.id)
            )
        elif command == "/journal":
            await self._send_student_journal(message)
            return True
        elif command == "/settings":
            journey = await self._students.get_journey(message.sender.id)
            response = self._settings_text(journey)
            if journey is not None:
                reply_markup = self._settings_reply_markup(journey)
        elif command == "/help":
            journey = await self._students.get_journey(message.sender.id)
            response = self._help_text(
                journey,
                is_reviewer=await self._reviews.is_reviewer(message.sender.id),
            )
        elif command == "/next":
            response = self._next_step_text(
                await self._students.get_journey(message.sender.id)
            )
        elif command == "/student_mode":
            journey = await self._students.get_journey(message.sender.id)
            response = (
                "🎓 <b>РЕЖИМ УЧЕНИКА</b>\n\n"
                "Здесь показан путь ученика: уроки, домашние задания и прогресс."
            )
            reply_markup = main_keyboard(
                journey,
                is_reviewer=await self._reviews.is_reviewer(message.sender.id),
            )
        elif command == "/curator_mode":
            if await self._reviews.is_reviewer(message.sender.id):
                response = (
                    "🧑‍💼 <b>РЕЖИМ КУРАТОРА</b>\n\n"
                    "Проверяй работы, открывай историю и следи за учениками."
                )
                reply_markup = curator_keyboard()
            else:
                response = "⛔ <b>Режим куратора недоступен.</b>"
        elif command == "/cancel":
            cancelled = await self._submissions.cancel(message.sender.id)
            response = (
                "✅ <b>Сдача отменена</b>"
                if cancelled
                else "ℹ️ Сейчас нет активной сдачи домашнего задания."
            )
        elif command == "/reviews":
            await self._send_review_queue(message)
            return True
        elif command == "/review_history":
            await self._send_review_history(message)
            return True
        elif command == "/curator_dashboard":
            response = await self._curator_summary(message.sender.id)
        elif command == "/curator_students":
            response = await self._curator_students(message.sender.id)
        elif command == "/grant_access":
            await self._send_grant_student_picker(message)
            return True
        elif command == "/course_videos":
            lessons = await self._learning.list_video_lessons(message.sender.id)
            response = "🎬 <b>ВИДЕО УРОКОВ</b>\n\nВыбери урок, затем отправь видео боту."
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": title[:60],
                            "callback_data": f"course_video:{lesson_id}",
                        }
                    ]
                    for lesson_id, title in lessons
                ]
            }
        elif (
            message.document is not None
            or message.photo
            or message.video is not None
            or message.video_note is not None
        ):
            response = await self._accept_attachment_submission(message.sender.id, message)
        elif command.startswith("/"):
            response = self._unknown_command_text()
        else:
            response = await self._accept_text_submission(
                message.sender.id,
                message.text or "",
            )

        if reply_markup is None:
            curator_commands = {
                "/reviews",
                "/review_history",
                "/curator_dashboard",
                "/curator_students",
                "/grant_access",
                "/cancel_review",
            }
            if (
                pending_feedback is not None or command in curator_commands
            ) and await self._reviews.is_reviewer(message.sender.id):
                reply_markup = curator_keyboard()
            else:
                reply_markup = await self._main_keyboard(message.sender.id)
        if lesson is not None and lesson.materials:
            await self._send_lesson_workspace(message.chat.id, lesson)
            return True
        if lesson_cover_url is not None:
            try:
                await self._api.send_photo(
                    message.chat.id,
                    lesson_cover_url,
                    caption=self._lesson_media_caption(lesson),
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except (TelegramAPIError, TelegramTransportError):
                pass
            else:
                if lesson is not None and lesson.assignment_instructions:
                    await self._api.send_message(
                        message.chat.id,
                        self._lesson_homework_text(lesson),
                        parse_mode="HTML",
                    )
                return True
        await self._api.send_message(
            message.chat.id,
            response,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options=link_preview_options,
        )
        return True

    async def _handle_settings_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False

        parts = callback.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        journey = await self._students.get_journey(callback.sender.id)
        if journey is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Сначала зарегистрируйся через /start",
                show_alert=True,
            )
            return True

        text = self._settings_text(journey)
        reply_markup = self._settings_reply_markup(journey)
        answer = ""

        try:
            if action == "menu" and len(parts) == 2:
                pass
            elif action == "timezone" and len(parts) == 2:
                text = f"{text}\n\n<b>Выбери свой часовой пояс:</b>"
                reply_markup = self._timezone_reply_markup(journey.timezone)
            elif action == "timezone" and len(parts) == 3:
                journey = await self._students.update_settings(
                    callback.sender.id,
                    timezone=parts[2],
                )
                answer = "Часовой пояс сохранён"
            elif action == "quiet" and len(parts) == 2:
                text = f"{text}\n\n<b>Когда не присылать уведомления:</b>"
                reply_markup = self._quiet_hours_reply_markup(
                    journey.quiet_hours_start,
                    journey.quiet_hours_end,
                )
            elif action == "quiet" and len(parts) == 4:
                journey = await self._students.update_settings(
                    callback.sender.id,
                    quiet_hours=(int(parts[2]), int(parts[3])),
                )
                answer = "Тихие часы сохранены"
            elif action == "reminders" and len(parts) == 3 and parts[2] in {"0", "1"}:
                journey = await self._students.update_settings(
                    callback.sender.id,
                    reminders_enabled=parts[2] == "1",
                )
                answer = "Напоминания включены" if parts[2] == "1" else "Напоминания отключены"
            else:
                raise ValueError
        except (InvalidQuietHoursError, InvalidTimezoneError, ValueError):
            await self._api.answer_callback_query(
                callback.id,
                text="Некорректная настройка",
                show_alert=True,
            )
            return True

        if journey is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Ученик не найден",
                show_alert=True,
            )
            return True

        if answer:
            text = self._settings_text(journey)
            reply_markup = self._settings_reply_markup(journey)
        await self._api.answer_callback_query(callback.id, text=answer or None)
        if callback.message is not None:
            await self._api.edit_message_text(
                callback.message.chat.id,
                callback.message.message_id,
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return True

    async def _handle_lesson_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False

        try:
            namespace, action, lesson_id_value = callback.data.split(":", maxsplit=2)
            if namespace != "lesson" or action not in {"viewed", "open", "locked"}:
                raise ValueError
            lesson_id = UUID(lesson_id_value)
        except ValueError:
            await self._api.answer_callback_query(
                callback.id,
                text="Некорректное действие",
                show_alert=True,
            )
            return True

        if action == "locked":
            await self._api.answer_callback_query(
                callback.id,
                text="Этот урок откроется позже",
                show_alert=True,
            )
            return True

        if action == "open":
            lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
            if lesson is None:
                await self._api.answer_callback_query(
                    callback.id,
                    text="Урок пока недоступен",
                    show_alert=True,
                )
                return True
            await self._api.answer_callback_query(callback.id)
            if callback.message is not None:
                telegram_source = self._telegram_lesson_source(lesson)
                if telegram_source is not None:
                    await self._api.copy_message(
                        callback.message.chat.id,
                        telegram_source[0],
                        telegram_source[1],
                    )
                reply_markup = (
                    self._lesson_reply_markup(lesson)
                    if lesson.is_current and lesson.viewed_at is None
                    else self._replay_lesson_reply_markup(lesson)
                )
                if lesson.materials:
                    await self._send_lesson_workspace(callback.message.chat.id, lesson)
                    return True
                link_preview_options = None
                if lesson.video_source.value == "external_url" and lesson.video_reference:
                    link_preview_options = {
                        "url": vimeo_watch_url(lesson.video_reference),
                        "prefer_large_media": True,
                        "show_above_text": True,
                    }
                    cover_url = await self._vimeo_thumbnail(lesson.video_reference)
                    if cover_url is not None:
                        try:
                            await self._api.send_photo(
                                callback.message.chat.id,
                                cover_url,
                                caption=self._lesson_media_caption(lesson),
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                            )
                        except (TelegramAPIError, TelegramTransportError):
                            pass
                        else:
                            if lesson.assignment_instructions:
                                await self._api.send_message(
                                    callback.message.chat.id,
                                    self._lesson_homework_text(lesson),
                                    parse_mode="HTML",
                                )
                            return True
                await self._api.send_message(
                    callback.message.chat.id,
                    self._lesson_text(lesson),
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    link_preview_options=link_preview_options,
                )
            return True

        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        if lesson is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Урок сейчас недоступен",
                show_alert=True,
            )
            return True

        if lesson.materials:
            viewed_count = sum(material.is_viewed for material in lesson.materials)
            total_count = len(lesson.materials)
            if viewed_count < total_count:
                await self._api.answer_callback_query(
                    callback.id,
                    text=(
                        "Сначала отметь все материалы урока. "
                        f"Сейчас отмечено {viewed_count}/{total_count}."
                    ),
                    show_alert=True,
                )
                return True

        try:
            result = await self._progression.mark_current_viewed(
                callback.sender.id,
                expected_lesson_id=lesson_id,
            )
        except LessonMismatchError:
            await self._api.answer_callback_query(
                callback.id,
                text="Этот урок уже пройден",
            )
            return True
        except ActiveLessonNotFoundError:
            await self._api.answer_callback_query(
                callback.id,
                text="Урок сейчас недоступен",
                show_alert=True,
            )
            return True

        await self._api.answer_callback_query(callback.id, text="Урок отмечен")
        if callback.message is not None:
            refreshed = await self._learning.get_available_lesson(
                callback.sender.id, lesson_id
            )
            await self._api.edit_message_reply_markup(
                callback.message.chat.id,
                callback.message.message_id,
                self._completed_lesson_reply_markup(refreshed or lesson),
            )
            homework_pending = (
                not result.course_completed
                and result.current_lesson_position == result.lesson_position
                and (refreshed or lesson).assignment_instructions is not None
            )
            if homework_pending:
                text = (
                    "✅ <b>МАТЕРИАЛЫ ОТМЕЧЕНЫ</b>\n\n"
                    "Осталось домашнее задание — открой его кнопкой ниже."
                )
                reply_markup: dict[str, object] = {
                    "inline_keyboard": [
                        [
                            {
                                "text": "📝 Открыть домашнее задание",
                                "callback_data": f"homework:{lesson_id}",
                            }
                        ]
                    ]
                }
            else:
                text = self._viewed_result_text(result)
                reply_markup = await self._main_keyboard(callback.sender.id)
            await self._api.send_message(
                callback.message.chat.id,
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return True

    async def _vimeo_thumbnail(self, video_url: str) -> str | None:
        if self._vimeo is None:
            return None
        metadata = await self._vimeo.get_metadata(video_url)
        return metadata.thumbnail_url if metadata is not None else None

    @staticmethod
    def _lesson_media_caption(lesson: CurrentLesson | None) -> str:
        if lesson is None:
            return "📚 <b>Урок недоступен</b>"
        status = "✅ пройдено" if lesson.viewed_at is not None else "⏳ ожидает просмотра"
        parts = [
            f"📘 <b>УРОК {lesson.position} ИЗ {lesson.total_lessons}</b>",
            f"🎓 {escape(lesson.course_title)}",
            f"<b>{escape(lesson.title)}</b>",
            f"Статус: <b>{status}</b>",
        ]
        if lesson.description:
            description = lesson.description[:650]
            if len(lesson.description) > len(description):
                description += "…"
            parts.append(escape(description))
        return "\n\n".join(parts)

    @staticmethod
    def _lesson_homework_text(lesson: CurrentLesson) -> str:
        instructions = escape(lesson.assignment_instructions or "")
        if not lesson.is_current:
            hint = "Это задание уже пройденного урока — оно доступно для повторения."
        elif lesson.requires_view_confirmation and lesson.viewed_at is None:
            hint = (
                "Сдача откроется после того, как отметишь все материалы и нажмёшь "
                "«✅ Я посмотрел все материалы»."
                if lesson.materials
                else "Сначала посмотри материал и отметь урок просмотренным."
            )
        else:
            hint = "Когда ответ будет готов, нажми «📤 Сдать ДЗ»."
        return f"📝 <b>ДОМАШНЕЕ ЗАДАНИЕ</b>\n\n{instructions}\n\n<i>{hint}</i>"

    async def _send_review_queue(self, message: TelegramMessage) -> None:
        if message.sender is None or not await self._reviews.is_reviewer(message.sender.id):
            await self._api.send_message(
                message.chat.id,
                "⛔ <b>Нет доступа к проверке работ.</b>",
                parse_mode="HTML",
                reply_markup=await self._main_keyboard(message.sender.id),
            )
            return

        queue = await self._reviews.list_pending(source=SubmissionSource.TELEGRAM)
        if not queue:
            await self._api.send_message(
                message.chat.id,
                "✅ <b>Очередь проверки пуста.</b>",
                parse_mode="HTML",
                reply_markup=curator_keyboard(),
            )
            return

        for item in queue:
            await self._api.send_message(
                message.chat.id,
                self._review_card_text(item),
                parse_mode="HTML",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "✅ Принять",
                                "callback_data": f"review:accept:{item.submission_id}",
                            },
                            {
                                "text": "🔄 На доработку",
                                "callback_data": f"review:revision:{item.submission_id}",
                            },
                        ]
                    ]
                },
            )
            attachments = await self._reviews.list_attachment_copies(item.submission_id)
            for attachment in attachments:
                try:
                    await self._api.copy_message(
                        message.chat.id,
                        attachment.source_chat_id,
                        attachment.source_message_id,
                    )
                except (TelegramAPIError, TelegramTransportError):
                    await self._api.send_message(
                        message.chat.id,
                        "⚠️ Не удалось показать одно из вложений. Открой работу в веб-кабинете.",
                    )

    async def _send_student_journal(self, message: TelegramMessage) -> None:
        if message.sender is None:
            return
        entries = await self._submissions.journal(message.sender.id)
        if not entries:
            await self._api.send_message(
                message.chat.id,
                "<b>PROJECT FIX / REVIEW LOG</b>\n\n"
                "Здесь появятся отправленные работы, решения куратора и замечания.",
                parse_mode="HTML",
                reply_markup=await self._main_keyboard(message.sender.id),
            )
            return
        await self._api.send_message(
            message.chat.id,
            "<b>PROJECT FIX / REVIEW LOG</b>\n\n"
            f"Последние работы: <b>{len(entries)}</b>",
            parse_mode="HTML",
        )
        status_labels = {
            SubmissionStatus.SUBMITTED: "WAITING",
            SubmissionStatus.IN_REVIEW: "IN REVIEW",
            SubmissionStatus.ACCEPTED: "ACCEPTED",
            SubmissionStatus.REVISION_REQUESTED: "REVISION",
        }
        for index, entry in enumerate(entries):
            feedback = (
                f"\n\n<b>Комментарий куратора</b>\n{escape(entry.feedback_message)}"
                if entry.feedback_message
                else ""
            )
            await self._api.send_message(
                message.chat.id,
                f"<b>FIX / LESSON {entry.lesson_position:02d}</b>\n"
                f"{escape(entry.lesson_title)}\n\n"
                f"ATTEMPT / {entry.attempt_number}\n"
                f"STATUS / <b>{status_labels[entry.status]}</b>\n"
                f"SENT / {entry.submitted_at:%d.%m.%Y %H:%M}"
                f"{feedback}",
                parse_mode="HTML",
                reply_markup=(
                    await self._main_keyboard(message.sender.id)
                    if index == len(entries) - 1
                    else None
                ),
            )
            for attachment in entry.feedback_attachments:
                try:
                    await self._send_feedback_attachment_copy(
                        message.chat.id, attachment
                    )
                except (TelegramAPIError, TelegramTransportError, OSError):
                    await self._api.send_message(
                        message.chat.id,
                        "⚠️ Не удалось показать вложение куратора. "
                        "Если оно нужно — напиши куратору.",
                    )

    async def _send_feedback_attachment_copy(
        self,
        chat_id: int,
        attachment: JournalFeedbackAttachment,
    ) -> None:
        if (
            attachment.source_chat_id is not None
            and attachment.source_message_id is not None
        ):
            await self._api.copy_message(
                chat_id,
                attachment.source_chat_id,
                attachment.source_message_id,
            )
            return
        if attachment.external_url is not None:
            await self._api.send_message(chat_id, attachment.external_url)
            return
        if attachment.local_path is not None:
            local_path = Path(attachment.local_path)
            if attachment.kind is AttachmentKind.PHOTO:
                await self._api.send_photo_file(
                    chat_id,
                    local_path,
                    mime_type=attachment.mime_type or "image/jpeg",
                )
            else:
                await self._api.send_document_file(
                    chat_id,
                    local_path,
                    mime_type=attachment.mime_type or "application/octet-stream",
                )

    async def _send_review_history(self, message: TelegramMessage) -> None:
        if message.sender is None or not await self._reviews.is_reviewer(message.sender.id):
            await self._api.send_message(
                message.chat.id,
                "⛔ <b>Нет доступа к истории проверок.</b>",
                parse_mode="HTML",
                reply_markup=await self._main_keyboard(message.sender.id),
            )
            return

        reviewed = [
            item
            for item in await self._reviews.list_pending(
                include_reviewed=True,
                limit=50,
                source=SubmissionSource.TELEGRAM,
            )
            if item.status
            in {SubmissionStatus.ACCEPTED, SubmissionStatus.REVISION_REQUESTED}
        ][:10]
        if not reviewed:
            await self._api.send_message(
                message.chat.id,
                "🗂 <b>Проверенных работ пока нет.</b>",
                parse_mode="HTML",
                reply_markup=curator_keyboard(),
            )
            return

        await self._api.send_message(
            message.chat.id,
            "🗂 <b>ПОСЛЕДНИЕ ПРОВЕРЕННЫЕ РАБОТЫ</b>\n\n"
            "Показаны последние 10 решений. Полная история доступна в веб-кабинете.",
            parse_mode="HTML",
        )
        for item in reviewed:
            await self._api.send_message(
                message.chat.id,
                self._review_history_card_text(item),
                parse_mode="HTML",
            )
        await self._api.send_message(
            message.chat.id,
            "Выбери следующий раздел:",
            reply_markup=curator_keyboard(),
        )

    async def _handle_review_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data or not callback.data.startswith("review:"):
            return False

        try:
            _, action, submission_id_value = callback.data.split(":", maxsplit=2)
            submission_id = UUID(submission_id_value)
            verdict = {
                "accept": FeedbackVerdict.ACCEPTED,
                "revision": FeedbackVerdict.REVISION_REQUESTED,
            }[action]
        except (ValueError, KeyError):
            await self._api.answer_callback_query(
                callback.id,
                text="Некорректное действие",
                show_alert=True,
            )
            return True

        if callback.message is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Карточка работы недоступна",
                show_alert=True,
            )
            return True
        try:
            await self._reviews.begin_telegram_feedback(
                submission_id=submission_id,
                reviewer_telegram_user_id=callback.sender.id,
                verdict=verdict,
                source_chat_id=callback.message.chat.id,
                source_message_id=callback.message.message_id,
            )
        except UnauthorizedReviewerError:
            await self._api.answer_callback_query(
                callback.id,
                text="Нет доступа",
                show_alert=True,
            )
            return True
        except SubmissionNotFoundError:
            await self._api.answer_callback_query(
                callback.id,
                text="Работа не найдена",
                show_alert=True,
            )
            return True
        except SubmissionAlreadyReviewedError:
            await self._api.answer_callback_query(
                callback.id,
                text="Работа уже проверена",
                show_alert=True,
            )
            return True

        verdict_text = "принятие работы" if verdict is FeedbackVerdict.ACCEPTED else "доработку"
        await self._api.answer_callback_query(callback.id, text="Теперь добавь комментарий")
        await self._api.edit_message_reply_markup(
            callback.message.chat.id,
            callback.message.message_id,
            {"inline_keyboard": []},
        )
        await self._api.send_message(
            callback.message.chat.id,
            "💬 <b>КОММЕНТАРИЙ УЧЕНИКУ</b>\n\n"
            f"Выбрано: <b>{verdict_text}</b>.\n"
            "Напиши обратную связь текстом или отправь фото/файл с подписью. "
            "Решение будет сохранено только после этого.\n\n"
            "Отмена: /cancel_review",
            parse_mode="HTML",
            reply_markup={
                "force_reply": True,
                "input_field_placeholder": "Комментарий ученику",
                "selective": True,
            },
        )
        return True

    async def _complete_review_feedback(
        self,
        reviewer_telegram_user_id: int,
        message: str,
        attachments: tuple[FeedbackAttachmentInput, ...] = (),
    ) -> str:
        try:
            completion = await self._reviews.complete_telegram_feedback(
                reviewer_telegram_user_id=reviewer_telegram_user_id,
                message=message,
                attachments=attachments,
            )
        except EmptyFeedbackError:
            return "⚠️ Комментарий пустой. Напиши текст или отправь фото/файл с пояснением."
        except SubmissionAlreadyReviewedError:
            await self._reviews.cancel_telegram_feedback(reviewer_telegram_user_id)
            return "ℹ️ Эта работа уже проверена другим куратором."
        except (SubmissionNotFoundError, UnauthorizedReviewerError):
            await self._reviews.cancel_telegram_feedback(reviewer_telegram_user_id)
            return "⛔ Не удалось сохранить решение. Работа или доступ больше недоступны."

        verdict_text = (
            "принята"
            if completion.result.verdict is FeedbackVerdict.ACCEPTED
            else "отправлена на доработку"
        )
        return (
            "✅ <b>РЕШЕНИЕ СОХРАНЕНО</b>\n\n"
            f"Работа {verdict_text}. Комментарий отправляется ученику."
        )

    async def _complete_review_feedback_from_message(
        self,
        reviewer_telegram_user_id: int,
        message: TelegramMessage,
    ) -> str:
        attachment = self._feedback_attachment_from_message(message)
        feedback_text = (message.text or message.caption or "").strip()
        return await self._complete_review_feedback(
            reviewer_telegram_user_id,
            feedback_text,
            (attachment,) if attachment is not None else (),
        )

    @staticmethod
    def _review_card_text(item: ReviewQueueItem) -> str:
        username = f"@{escape(item.student_username)}" if item.student_username else "нет"
        answer = escape(item.text_body) if item.text_body else "Текстового ответа нет"
        if len(answer) > 1200:
            answer = f"{answer[:1200]}…"
        return (
            "📥 <b>ДЗ НА ПРОВЕРКУ</b>\n\n"
            f"👤 {escape(item.student_name)} ({username})\n"
            f"🎓 {escape(item.course_title)}\n"
            f"📘 Урок {item.lesson_position}: {escape(item.lesson_title)}\n"
            f"🔁 Попытка: {item.attempt_number}\n"
            f"📎 Вложений: {item.attachment_count}\n\n"
            f"📝 <b>Ответ ученика</b>\n{answer}"
        )

    @staticmethod
    def _review_history_card_text(item: ReviewQueueItem) -> str:
        verdict = (
            "✅ принято"
            if item.status is SubmissionStatus.ACCEPTED
            else "🔄 отправлено на доработку"
        )
        return (
            f"{verdict}\n"
            f"👤 <b>{escape(item.student_name)}</b>\n"
            f"📘 Урок {item.lesson_position}: {escape(item.lesson_title)}\n"
            f"🎓 {escape(item.course_title)} · попытка {item.attempt_number}"
        )

    @staticmethod
    def _extract_command(text: str) -> str:
        normalized_text = text.strip().casefold()
        project_fix_commands = {
            "▶ продолжить": "/lesson",
            "📘 текущий урок": "/lesson",
            "▦ мой прогресс": "/progress",
            "📊 мой прогресс": "/progress",
            "▤ программа курса": "/lessons",
            "📚 программа курса": "/lessons",
            "▣ мои разборы": "/journal",
            "🗂 мои разборы": "/journal",
            "📥 сдать работу": "/submit",
            "📥 сдать дз": "/submit",
            "↻ отправить доработку": "/submit",
            "🔄 отправить доработку": "/submit",
            "⏳ статус работы": "/status",
            "⏳ статус дз": "/status",
            "⚙ настройки": "/settings",
            "⚙️ настройки": "/settings",
            "? помощь": "/help",
            "ℹ️ помощь": "/help",
            "📚 база материалов": "/lessons",
            "режим куратора": "/curator_mode",
        }
        if normalized_text in project_fix_commands:
            return project_fix_commands[normalized_text]
        button_commands = {
            "📘 открыть урок": "/lesson",
            "📘 текущий урок": "/lesson",
            "📚 о курсе": "/course",
            "📊 мой прогресс": "/progress",
            "📤 сдать дз": "/submit",
            "🔄 отправить доработку": "/submit",
            "⏳ статус дз": "/status",
            "⚙️ настройки": "/settings",
            "ℹ️ помощь": "/help",
            "🏆 итоги курса": "/progress",
            "🚀 что дальше": "/next",
            "📥 очередь проверки": "/reviews",
            "🗂 проверенные": "/review_history",
            "📊 сводка куратора": "/curator_dashboard",
            "👥 ученики": "/curator_students",
            "🎓 выдать доступ": "/grant_access",
            "🎬 видео уроков": "/course_videos",
            "🎓 режим ученика": "/student_mode",
            "🧑‍💼 режим куратора": "/curator_mode",
        }
        if normalized_text == "📖 все уроки".casefold():
            return "/lessons"
        if normalized_text in button_commands:
            return button_commands[normalized_text]

        first_word = normalized_text.split(maxsplit=1)[0]
        return first_word.split("@", maxsplit=1)[0]

    async def _main_keyboard(self, telegram_user_id: int) -> dict[str, object]:
        journey = await self._students.get_journey(telegram_user_id)
        return main_keyboard(
            journey,
            is_reviewer=await self._reviews.is_reviewer(telegram_user_id),
        )

    async def _curator_summary(self, telegram_user_id: int) -> str:
        if not await self._reviews.is_reviewer(telegram_user_id):
            return "⛔ <b>Нет доступа к сводке куратора.</b>"
        summary = await self._dashboard.summary()
        return (
            "📊 <b>СВОДКА КУРАТОРА</b>\n\n"
            f"📥 Ожидают проверки: <b>{summary.pending_reviews}</b>\n"
            f"👥 Активных учеников: <b>{summary.active_students}</b>\n"
            f"📈 Средний прогресс: <b>{summary.average_progress_percent}%</b>\n"
            f"🏆 Завершили курс: <b>{summary.completed_enrollments}</b>\n"
            f"🎓 Активных курсов: <b>{summary.active_courses}</b>"
        )

    async def _curator_students(self, telegram_user_id: int) -> str:
        if not await self._reviews.is_reviewer(telegram_user_id):
            return "⛔ <b>Нет доступа к списку учеников.</b>"
        students = await self._dashboard.list_students()
        if not students:
            return "👥 <b>Учеников пока нет.</b>"
        lines = ["👥 <b>УЧЕНИКИ</b>", ""]
        for student in students[:15]:
            marker = "✅" if student.progress_percent == 100 else "📘"
            lines.append(
                f"{marker} <b>{escape(student.name)}</b> — "
                f"{student.progress_percent}% · урок {student.current_lesson_position or '—'}"
            )
        if len(students) > 15:
            lines.extend(
                [
                    "",
                    f"Ещё учеников: {len(students) - 15}. "
                    "Полный список — в веб-кабинете.",
                ]
            )
        return "\n".join(lines)

    async def _send_grant_student_picker(self, message: TelegramMessage) -> None:
        if message.sender is None or not await self._reviews.is_reviewer(message.sender.id):
            await self._api.send_message(
                message.chat.id,
                "⛔ <b>Нет доступа к выдаче курсов.</b>",
                parse_mode="HTML",
                reply_markup=await self._main_keyboard(message.sender.id if message.sender else 0),
            )
            return
        if self._access is None:
            await self._api.send_message(
                message.chat.id,
                "⚠️ <b>Выдача курсов временно недоступна.</b>",
                parse_mode="HTML",
                reply_markup=curator_keyboard(),
            )
            return

        students = await self._access.list_telegram_students_for_grant()
        if not students:
            await self._api.send_message(
                message.chat.id,
                "👥 <b>Нет Telegram-учеников для выдачи доступа.</b>\n\n"
                "Ученик должен сначала нажать /start в боте.",
                parse_mode="HTML",
                reply_markup=curator_keyboard(),
            )
            return

        session: dict[str, UUID] = {}
        rows: list[list[dict[str, object]]] = []
        for index, student in enumerate(students, start=1):
            key = f"s{index}"
            session[key] = student.student_id
            rows.append(
                [
                    {
                        "text": self._grant_student_button_text(
                            student.name,
                            student.username,
                            student.course_title,
                        ),
                        "callback_data": f"grant:student:{key}",
                    }
                ]
            )
        self._grant_sessions[message.sender.id] = session
        self._grant_selected_students.pop(message.sender.id, None)

        await self._api.send_message(
            message.chat.id,
            "🎓 <b>Выдать доступ к курсу</b>\n\n"
            "Шаг 1 из 3: выбери Telegram-ученика.\n"
            "Если ученика нет в списке — он должен сначала нажать /start в боте.",
            parse_mode="HTML",
            reply_markup={"inline_keyboard": rows},
        )

    async def _handle_grant_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or callback.data is None:
            return False
        if not await self._reviews.is_reviewer(callback.sender.id):
            await self._api.answer_callback_query(
                callback.id,
                text="Нет доступа к выдаче курсов",
                show_alert=True,
            )
            return True
        if self._access is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Выдача курсов временно недоступна",
                show_alert=True,
            )
            return True

        parts = callback.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "student" and len(parts) == 3:
            await self._api.answer_callback_query(callback.id)
            await self._send_grant_course_picker(callback, parts[2])
            return True
        if action == "course" and len(parts) == 3:
            await self._api.answer_callback_query(callback.id)
            await self._send_grant_confirmation(callback, parts[2])
            return True
        if action == "confirm":
            await self._confirm_grant(callback)
            return True
        if action == "cancel":
            self._grant_sessions.pop(callback.sender.id, None)
            self._grant_selected_students.pop(callback.sender.id, None)
            await self._api.answer_callback_query(callback.id, text="Отменено")
            if callback.message is not None:
                await self._api.send_message(
                    callback.message.chat.id,
                    "Выдача доступа отменена.",
                    reply_markup=curator_keyboard(),
                )
            return True

        await self._api.answer_callback_query(
            callback.id,
            text="Действие устарело. Открой «Выдать доступ» заново.",
            show_alert=True,
        )
        return True

    async def _send_grant_course_picker(
        self,
        callback: TelegramCallbackQuery,
        student_key: str,
    ) -> None:
        sender = callback.sender
        message = callback.message
        session = self._grant_sessions.get(sender.id, {})
        student_id = session.get(student_key)
        if student_id is None or message is None:
            await self._api.send_message(
                sender.id,
                "⚠️ Сессия выдачи устарела. Нажми «🎓 Выдать доступ» заново.",
                reply_markup=curator_keyboard(),
            )
            return
        courses = await self._access.list_telegram_courses_for_grant() if self._access else ()
        if not courses:
            await self._api.send_message(
                message.chat.id,
                "📚 <b>Нет активных Telegram-курсов.</b>\n\n"
                "Курс нужно создать и опубликовать в веб-панели.",
                parse_mode="HTML",
                reply_markup=curator_keyboard(),
            )
            return

        self._grant_selected_students[sender.id] = student_id
        rows: list[list[dict[str, object]]] = []
        for index, course in enumerate(courses, start=1):
            key = f"c{index}"
            session[key] = course.course_id
            rows.append(
                [
                    {
                        "text": self._grant_course_button_text(
                            course.title,
                            course.lessons_count,
                            course.students_count,
                        ),
                        "callback_data": f"grant:course:{key}",
                    }
                ]
            )
        self._grant_sessions[sender.id] = session

        await self._api.send_message(
            message.chat.id,
            "🎓 <b>Выдать доступ к курсу</b>\n\n"
            "Шаг 2 из 3: выбери Telegram-курс.\n"
            "Создание и редактирование курсов остаётся в веб-панели.",
            parse_mode="HTML",
            reply_markup={"inline_keyboard": rows},
        )

    async def _send_grant_confirmation(
        self,
        callback: TelegramCallbackQuery,
        course_key: str,
    ) -> None:
        sender = callback.sender
        message = callback.message
        session = self._grant_sessions.get(sender.id, {})
        student_id = self._grant_selected_students.get(sender.id)
        course_id = session.get(course_key)
        if student_id is None or course_id is None or message is None:
            await self._api.send_message(
                sender.id,
                "⚠️ Сессия выдачи устарела. Нажми «🎓 Выдать доступ» заново.",
                reply_markup=curator_keyboard(),
            )
            return
        session["selected_course"] = course_id
        self._grant_sessions[sender.id] = session

        await self._api.send_message(
            message.chat.id,
            "✅ <b>Подтверди выдачу доступа</b>\n\n"
            "После подтверждения ученик получит уведомление в Telegram "
            "и сможет открыть текущий урок.\n\n"
            "<i>Если у ученика уже был другой Telegram-курс, активный курс будет заменён.</i>",
            parse_mode="HTML",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "✅ Выдать доступ", "callback_data": "grant:confirm"}],
                    [{"text": "Отмена", "callback_data": "grant:cancel"}],
                ]
            },
        )

    async def _confirm_grant(self, callback: TelegramCallbackQuery) -> None:
        sender = callback.sender
        message = callback.message
        session = self._grant_sessions.get(sender.id, {})
        student_id = self._grant_selected_students.get(sender.id)
        course_id = session.get("selected_course")
        if self._access is None or student_id is None or course_id is None:
            await self._api.answer_callback_query(
                callback.id,
                text="Сессия выдачи устарела",
                show_alert=True,
            )
            return

        try:
            detail = await self._access.grant_telegram_course(
                student_id=student_id,
                course_id=course_id,
            )
        except StudentAccessError:
            await self._api.answer_callback_query(
                callback.id,
                text="Не удалось выдать доступ",
                show_alert=True,
            )
            return

        self._grant_sessions.pop(sender.id, None)
        self._grant_selected_students.pop(sender.id, None)
        await self._api.answer_callback_query(
            callback.id,
            text="Доступ выдан",
        )
        chat_id = message.chat.id if message is not None else sender.id
        await self._api.send_message(
            chat_id,
            "✅ <b>Доступ выдан</b>\n\n"
            f"Ученик: <b>{escape(getattr(detail, 'name', 'Telegram ученик'))}</b>\n"
            f"Курс: <b>{escape(getattr(detail, 'course_title', 'Telegram курс'))}</b>\n\n"
            "Ученик получит уведомление и кнопку для открытия текущего урока.",
            parse_mode="HTML",
            reply_markup=curator_keyboard(),
        )

    @staticmethod
    def _grant_student_button_text(
        name: str,
        username: str | None,
        course_title: str | None,
    ) -> str:
        identity = f"{name} · @{username}" if username else name
        status = course_title or "без курса"
        return f"{identity} · {status}"[:64]

    @staticmethod
    def _grant_course_button_text(
        title: str,
        lessons_count: int,
        students_count: int,
    ) -> str:
        return f"{title} · {lessons_count} уроков · {students_count} учеников"[:64]

    @staticmethod
    def _student_registration(user: TelegramUser) -> StudentRegistration:
        return StudentRegistration(
            telegram_user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code,
        )

    @staticmethod
    def _progress_text(progress: ProgressSnapshot | None) -> str:
        if progress is None:
            return (
                "✅ <b>Регистрация завершена</b>\n\n"
                "Курс пока не назначен. После выдачи доступа он появится здесь."
            )

        if progress.total_lessons == 0:
            return (
                f"🎓 <b>{escape(progress.course_title)}</b>\n\n"
                "Материалы курса пока не опубликованы."
            )

        if progress.is_completed:
            return (
                f"🏆 <b>КУРС ЗАВЕРШЁН</b>\n\n"
                f"🎓 <b>{escape(progress.course_title)}</b>\n\n"
                f"📘 Пройдено уроков: <b>{progress.total_lessons} "
                f"из {progress.total_lessons}</b>\n"
                f"✅ Принято ДЗ: <b>{progress.accepted_submissions} "
                f"из {progress.total_assignments}</b>\n\n"
                "Все материалы остаются доступными в «📚 Программа курса»."
            )

        current_position = min(progress.current_lesson_position, progress.total_lessons)
        if progress.total_assignments:
            percentage = round(progress.accepted_submissions / progress.total_assignments * 100)
        else:
            percentage = 0
        filled_segments = min(10, percentage // 10)
        progress_bar = "█" * filled_segments + "░" * (10 - filled_segments)

        return (
            f"🎓 <b>{escape(progress.course_title)}</b>\n\n"
            f"📈 <b>Прогресс курса</b>\n"
            f"<code>{progress_bar}</code>  {percentage}%\n\n"
            f"📍 Текущий урок: <b>{current_position} из {progress.total_lessons}</b>\n"
            f"✅ Принято ДЗ: <b>{progress.accepted_submissions} "
            f"из {progress.total_assignments}</b>\n\n"
            "Нажми «📘 Текущий урок», чтобы продолжить."
        )

    @staticmethod
    def _student_dashboard_text(
        progress: ProgressSnapshot | None, journey: StudentJourney | None
    ) -> str:
        if progress is None or journey is None:
            return (
                "<b>PROJECT FIX / ACCESS</b>\n\n"
                "Регистрация завершена. Курс появится после выдачи доступа."
            )
        current = min(progress.current_lesson_position, progress.total_lessons)
        percentage = (
            round(progress.accepted_submissions / progress.total_assignments * 100)
            if progress.total_assignments
            else 0
        )
        filled = min(10, percentage // 10)
        bar = "■" * filled + "□" * (10 - filled)
        stage_label = {
            StudentStage.NEEDS_VIEW: "LEARNING",
            StudentStage.READY_TO_SUBMIT: "READY TO SUBMIT",
            StudentStage.AWAITING_REVIEW: "UNDER REVIEW",
            StudentStage.REVISION_REQUESTED: "REVISION",
            StudentStage.COURSE_COMPLETED: "COMPLETED",
            StudentStage.LESSON_LOCKED: "LOCKED",
            StudentStage.NO_COURSE: "NO ACCESS",
        }[journey.stage]
        lesson_title = escape(journey.lesson_title or "Курс завершён")
        return (
            "<b>PROJECT FIX / STUDENT DESK</b>\n"
            f"{escape(progress.course_title)}\n\n"
            f"STATUS / <b>{stage_label}</b>\n"
            f"<code>{bar}</code> {percentage}%\n\n"
            f"STEP {current:02d} OF {progress.total_lessons:02d}\n"
            f"<b>{lesson_title}</b>\n\n"
            f"ACCEPTED / {progress.accepted_submissions} OF "
            f"{progress.total_assignments}\n\n"
            "Нажми «▶ Продолжить», чтобы открыть рабочее пространство недели."
        )

    @staticmethod
    def _course_outline_text(outline: CourseOutline | None) -> str:
        if outline is None:
            return (
                "📚 <b>КУРС ПОКА НЕ НАЗНАЧЕН</b>\n\n"
                "После выдачи доступа здесь появятся описание и программа."
            )
        lines = [
            f"📚 <b>{escape(outline.title)}</b>",
            "",
        ]
        if outline.description:
            lines.extend([escape(outline.description), ""])
        lines.append(f"📘 Уроков в программе: <b>{outline.total_lessons}</b>")
        lines.append("")
        for lesson in outline.lessons:
            marker = "▶️" if lesson.is_current else "▫️"
            suffix = " · текущий" if lesson.is_current else ""
            lines.append(
                f"{marker} <b>{lesson.position}. {escape(lesson.title)}</b>{suffix}"
            )
        return "\n".join(lines)

    @staticmethod
    def _journey_hint(journey: StudentJourney | None) -> str:
        if journey is None or journey.stage is StudentStage.NO_COURSE:
            return "🧭 <b>Следующий шаг:</b> дождаться назначения курса."
        hints = {
            StudentStage.COURSE_COMPLETED: (
                "🏆 <b>Курс завершён.</b> Все обязательные шаги выполнены."
            ),
            StudentStage.LESSON_LOCKED: (
                "🕒 <b>Следующий шаг:</b> дождаться открытия урока по расписанию."
            ),
            StudentStage.NEEDS_VIEW: "🧭 <b>Следующий шаг:</b> открыть урок и отметить просмотр.",
            StudentStage.READY_TO_SUBMIT: (
                "🧭 <b>Следующий шаг:</b> выполнить и отправить домашнее задание."
            ),
            StudentStage.AWAITING_REVIEW: "⏳ <b>Следующий шаг:</b> дождаться ответа куратора.",
            StudentStage.REVISION_REQUESTED: (
                "🔄 <b>Следующий шаг:</b> отправить исправленную работу."
            ),
        }
        return hints[journey.stage]

    @classmethod
    def _help_text(
        cls,
        journey: StudentJourney | None,
        *,
        is_reviewer: bool,
    ) -> str:
        lines = [
            "ℹ️ <b>КАК РАБОТАЕТ ОБУЧЕНИЕ</b>",
            "",
            "1. Открой текущий урок.",
            "2. Изучи материал и отметь просмотр.",
            "3. Отправь домашнее задание, если оно есть.",
            "4. Дождись ответа куратора или отправь исправленную работу.",
            "",
            cls._journey_hint(journey),
            "",
            "Команды: /lesson · /progress · /status · /settings",
        ]
        if is_reviewer:
            lines.extend(
                [
                    "",
                    "<b>Куратору:</b> /reviews · /review_history · "
                    "/curator_dashboard · /curator_students · /grant_access",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _next_step_text(journey: StudentJourney | None) -> str:
        if journey is None or journey.stage is StudentStage.NO_COURSE:
            return (
                "🧭 <b>Следующий шаг появится после назначения курса.</b>\n\n"
                "Пока можно проверить настройки уведомлений."
            )
        if journey.stage is not StudentStage.COURSE_COMPLETED:
            return (
                "🧭 <b>Сначала заверши текущий этап курса.</b>\n\n"
                f"{MessageRouter._journey_hint(journey)}"
            )
        return (
            "🚀 <b>КУРС ЗАВЕРШЁН — ЧТО ДАЛЬШЕ?</b>\n\n"
            "Все обязательные уроки и задания завершены. Здесь можно будет "
            "разместить сертификат, следующий продукт или персональную рекомендацию.\n\n"
            "Пока следующий шаг уточняется — куратор свяжется с тобой отдельно."
        )

    @classmethod
    def _journey_status_text(cls, journey: StudentJourney | None) -> str:
        if journey is None or journey.stage is StudentStage.NO_COURSE:
            return "ℹ️ <b>Курс пока не назначен.</b>"
        lesson = (
            f"Урок {journey.lesson_position}: {escape(journey.lesson_title or 'Без названия')}"
            if journey.lesson_position is not None
            else "Текущий урок не назначен"
        )
        return (
            "🧭 <b>ТЕКУЩИЙ СТАТУС</b>\n\n"
            f"🎓 {escape(journey.course_title or 'Курс')}\n"
            f"📘 {lesson}\n\n"
            f"{cls._journey_hint(journey)}"
        )

    @staticmethod
    def _settings_text(journey: StudentJourney | None) -> str:
        if journey is None:
            return "⚙️ <b>Настройки появятся после регистрации через /start.</b>"
        reminder_status = "включены ✅" if journey.reminders_enabled else "отключены"
        quiet_hours = (
            "выключены"
            if journey.quiet_hours_start == journey.quiet_hours_end
            else (
                f"с {journey.quiet_hours_start:02d}:00 "
                f"до {journey.quiet_hours_end:02d}:00"
            )
        )
        return (
            "⚙️ <b>НАСТРОЙКИ ОБУЧЕНИЯ</b>\n\n"
            f"🌍 Часовой пояс: <b>{escape(journey.timezone)}</b>\n"
            f"🌙 Тихие часы: <b>{quiet_hours}</b>\n"
            f"🔔 Напоминания: <b>{reminder_status}</b>\n\n"
            "Выбери параметр, который хочешь изменить."
        )

    @staticmethod
    def _settings_reply_markup(journey: StudentJourney) -> dict[str, object]:
        reminder_button = (
            {"text": "🔕 Отключить напоминания", "callback_data": "settings:reminders:0"}
            if journey.reminders_enabled
            else {"text": "🔔 Включить напоминания", "callback_data": "settings:reminders:1"}
        )
        return {
            "inline_keyboard": [
                [{"text": "🌍 Часовой пояс", "callback_data": "settings:timezone"}],
                [{"text": "🌙 Тихие часы", "callback_data": "settings:quiet"}],
                [reminder_button],
            ]
        }

    @staticmethod
    def _timezone_reply_markup(current_timezone: str) -> dict[str, object]:
        options = (
            ("Киев", "Europe/Kyiv"),
            ("Варшава", "Europe/Warsaw"),
            ("Берлин", "Europe/Berlin"),
            ("Лондон", "Europe/London"),
            ("Москва", "Europe/Moscow"),
            ("UTC", "UTC"),
        )
        buttons = [
            {
                "text": f"{'✓ ' if timezone == current_timezone else ''}{label}",
                "callback_data": f"settings:timezone:{timezone}",
            }
            for label, timezone in options
        ]
        return {
            "inline_keyboard": [
                buttons[index : index + 2] for index in range(0, len(buttons), 2)
            ]
            + [[{"text": "← Назад", "callback_data": "settings:menu"}]]
        }

    @staticmethod
    def _quiet_hours_reply_markup(current_start: int, current_end: int) -> dict[str, object]:
        options = (
            ("21:00 — 08:00", 21, 8),
            ("22:00 — 09:00", 22, 9),
            ("23:00 — 08:00", 23, 8),
            ("00:00 — 08:00", 0, 8),
            ("Без тихих часов", 0, 0),
        )
        rows = [
            [
                {
                    "text": (
                        f"{'✓ ' if (start, end) == (current_start, current_end) else ''}"
                        f"{label}"
                    ),
                    "callback_data": f"settings:quiet:{start}:{end}",
                }
            ]
            for label, start, end in options
        ]
        rows.append([{"text": "← Назад", "callback_data": "settings:menu"}])
        return {"inline_keyboard": rows}

    @classmethod
    def _lesson_unavailable_text(cls, journey: StudentJourney | None) -> str:
        if journey is None or journey.stage is StudentStage.NO_COURSE:
            return (
                "🔒 <b>Урок пока недоступен</b>\n\n"
                "Сначала зарегистрируйся через /start или дождись назначения курса."
            )
        if journey.stage is StudentStage.COURSE_COMPLETED:
            return (
                "🏆 <b>Курс завершён</b>\n\n"
                "Все обязательные уроки пройдены. Пересмотреть материалы можно "
                "через «📚 Программа курса»."
            )
        if journey.stage is StudentStage.LESSON_LOCKED:
            lesson_line = (
                f"📘 Урок {journey.lesson_position}: "
                f"<b>{escape(journey.lesson_title)}</b> — пройден.\n\n"
                if journey.lesson_position is not None and journey.lesson_title
                else ""
            )
            return (
                "✅ <b>Текущий урок пройден</b>\n\n"
                f"{lesson_line}"
                "Следующий урок откроется по расписанию — бот пришлёт уведомление. "
                "Пройденные уроки доступны в «📚 Программа курса»."
            )
        return f"🔒 <b>Урок сейчас недоступен</b>\n\n{cls._journey_hint(journey)}"

    @staticmethod
    def _lesson_text(lesson: CurrentLesson | None) -> str:
        if lesson is None:
            return (
                "🔒 <b>Урок пока недоступен</b>\n\n"
                "Сначала зарегистрируйся через /start или дождись назначения курса."
            )

        if lesson.video_source.value == "external_url" and lesson.video_reference:
            video_url = escape(vimeo_watch_url(lesson.video_reference), quote=True)
            video_text = f'🎬 <b>Видео</b>\n<a href="{video_url}">Открыть урок</a>'
        elif lesson.video_source.value == "telegram_channel":
            video_text = "🎬 <b>Видео</b>\nМатериал подготовлен в Telegram."
        else:
            video_text = "🎬 <b>Видео</b>\nДемонстрационная заглушка."

        parts = [
            f"📘 <b>УРОК {lesson.position} ИЗ {lesson.total_lessons}</b>",
            f"🎓 {escape(lesson.course_title)}",
            f"<b>{escape(lesson.title)}</b>",
            (
                "✅ <b>Статус:</b> просмотрено"
                if lesson.viewed_at is not None
                else "⏳ <b>Статус:</b> ожидает просмотра"
            ),
        ]
        if lesson.description:
            parts.append(escape(lesson.description))
        parts.append(video_text)
        if lesson.assignment_instructions:
            action_hint = (
                "Сначала посмотри материал и нажми «✅ Я посмотрел материал»."
                if lesson.requires_view_confirmation and lesson.viewed_at is None
                else "Когда ответ будет готов, нажми «📤 Сдать ДЗ»."
            )
            parts.append(
                "📝 <b>Домашнее задание</b>\n"
                f"{escape(lesson.assignment_instructions)}\n\n"
                f"{action_hint}"
            )
        else:
            parts.append(
                "📝 <b>Домашнее задание:</b> нет\n"
                "Сдавать ничего не нужно. После просмотра отметь материал."
            )

        return "\n\n".join(parts)

    async def _send_lesson_workspace(self, chat_id: int, lesson: CurrentLesson) -> None:
        status = "просмотрен" if lesson.viewed_at is not None else "нужно посмотреть"
        viewed_count = sum(material.is_viewed for material in lesson.materials)
        material_count = len(lesson.materials)
        progress_bar = "■" * viewed_count + "□" * (material_count - viewed_count)
        video_count = sum(material.kind == "video" for material in lesson.materials)
        image_count = sum(material.kind == "image" for material in lesson.materials)
        material_summary = f"🎬 видео: {video_count}"
        if image_count:
            material_summary += f" · 🖼 изображения: {image_count}"
        if lesson.assignment_instructions is None:
            homework_text = (
                "📝 <b>Домашнее задание:</b> нет\n"
                "Сдавать ничего не нужно. Достаточно посмотреть материалы урока."
            )
        elif lesson.viewed_at is None:
            homework_text = (
                "📝 <b>Домашнее задание:</b> есть\n"
                "Прочитать его можно сразу, а сдать — после отметки всех материалов."
            )
        else:
            homework_text = (
                "📝 <b>Домашнее задание:</b> есть\n"
                "Материалы просмотрены — можно сдавать ответ."
            )
        description = escape(lesson.description or "Описание урока скоро появится.")
        if lesson.viewed_at is None:
            if viewed_count < material_count:
                next_step = (
                    "Шаг 1: открой материалы ниже и отметь просмотр каждого. "
                    f"Сейчас отмечено {viewed_count}/{material_count}."
                )
            else:
                next_step = (
                    "Шаг 2: все материалы отмечены. Нажми "
                    "«✅ Я посмотрел все материалы», чтобы завершить урок."
                )
        elif lesson.assignment_instructions:
            next_step = "Шаг 3: открой «📝 Домашнее задание» и сдай ответ."
        else:
            next_step = "Урок завершён. ДЗ в этом уроке нет."
        caption = (
            f"📘 <b>Урок {lesson.position} из {lesson.total_lessons}</b>\n"
            f"Курс: <b>{escape(lesson.course_title)}</b>\n\n"
            f"<b>{escape(lesson.title)}</b>\n"
            f"{material_summary}\n"
            f"Статус: <b>{status}</b>\n"
            f"Прогресс материалов: {progress_bar} {viewed_count}/{material_count}\n"
            f"{homework_text}\n\n"
            f"{description}\n\n"
            f"<i>{escape(next_step)}</i>"
        )
        rows = [
            [
                {
                    "text": (
                        f"{'✓' if material.is_viewed else '○'} "
                        f"{'🖼' if material.kind == 'image' else '▶️'} "
                        f"{material.position}. {material.title}"
                    )[:64],
                    "callback_data": (
                        f"material:{lesson.lesson_id}:{material.position}"
                    ),
                }
            ]
            for material in lesson.materials
        ]
        if lesson.assignment_instructions:
            rows.append(
                [
                    {
                        "text": "📝 Домашнее задание",
                        "callback_data": f"homework:{lesson.lesson_id}",
                    }
                ]
            )
            rows.append(
                [
                    {
                        "text": "▣ Шаблон ответа",
                        "callback_data": f"template:{lesson.lesson_id}",
                    }
                ]
            )
        if (
            lesson.is_current
            and lesson.viewed_at is None
            and viewed_count == material_count
        ):
            # Fallback for cards left in the «all marked, not finished» state;
            # the happy path completes the lesson on the last material mark.
            rows.append(
                [
                    {
                        "text": "✅ Я посмотрел все материалы",
                        "callback_data": f"lesson:viewed:{lesson.lesson_id}",
                    }
                ]
            )
        reply_markup = {"inline_keyboard": rows}
        first = lesson.materials[0]
        cover_url = (
            await self._vimeo_thumbnail(first.video_reference)
            if first.video_source.value == "external_url" and first.video_reference
            else None
        )
        if cover_url is not None:
            try:
                await self._api.send_photo(
                    chat_id,
                    cover_url,
                    caption=caption[:1024],
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
            except (TelegramAPIError, TelegramTransportError):
                pass
        await self._api.send_message(
            chat_id,
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    async def _handle_material_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False
        try:
            _, lesson_id_value, position_value = callback.data.split(":", maxsplit=2)
            lesson_id = UUID(lesson_id_value)
            position = int(position_value)
        except ValueError:
            await self._api.answer_callback_query(callback.id, text="Материал не найден")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        material = next(
            (item for item in lesson.materials if item.position == position),
            None,
        ) if lesson is not None else None
        if lesson is None or material is None or callback.message is None:
            await self._api.answer_callback_query(
                callback.id, text="Материал пока недоступен", show_alert=True
            )
            return True
        await self._api.answer_callback_query(callback.id)
        description = (
            f"\n\n{escape(material.description)}" if material.description else ""
        )
        caption = (
            f"{'🖼' if material.kind == 'image' else '🎬'} "
            f"<b>Материал {material.position} из {len(lesson.materials)}</b>\n"
            f"Урок {lesson.position}: <b>{escape(lesson.title)}</b>\n\n"
            f"<b>{escape(material.title)}</b>{description}"
        )
        rows: list[list[dict[str, object]]] = []
        if material.kind == "video" and material.video_reference:
            rows.append(
                [{"text": "▶ Смотреть видео", "url": vimeo_watch_url(material.video_reference)}]
            )
        if not material.is_viewed:
            rows.append(
                [
                    {
                        "text": "✅ Я посмотрел этот материал",
                        "callback_data": (
                            f"matview:{lesson.lesson_id}:{material.position}"
                        ),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "← К уроку",
                    "callback_data": f"lesson:open:{lesson.lesson_id}",
                }
            ]
        )
        reply_markup = {"inline_keyboard": rows}
        if material.kind == "image" and material.video_reference:
            root = Path.cwd().resolve()
            image_path = (root / material.video_reference).resolve()
            if image_path.is_relative_to(root) and image_path.is_file():
                try:
                    await self._api.send_photo_file(
                        callback.message.chat.id,
                        image_path,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                    return True
                except (TelegramAPIError, TelegramTransportError):
                    pass
        cover_url = (
            await self._vimeo_thumbnail(material.video_reference)
            if material.video_source.value == "external_url" and material.video_reference
            else None
        )
        if cover_url is not None:
            try:
                await self._api.send_photo(
                    callback.message.chat.id,
                    cover_url,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return True
            except (TelegramAPIError, TelegramTransportError):
                pass
        await self._api.send_message(
            callback.message.chat.id,
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return True

    async def _handle_material_viewed_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False
        try:
            _, lesson_id_value, position_value = callback.data.split(":", maxsplit=2)
            lesson_id = UUID(lesson_id_value)
            position = int(position_value)
        except ValueError:
            await self._api.answer_callback_query(callback.id, text="Материал не найден")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        material = next(
            (item for item in lesson.materials if item.position == position), None
        ) if lesson is not None else None
        if lesson is None or material is None:
            await self._api.answer_callback_query(
                callback.id, text="Материал пока недоступен", show_alert=True
            )
            return True
        if not await self._learning.mark_material_viewed(
            callback.sender.id, material.material_id
        ):
            await self._api.answer_callback_query(
                callback.id, text="Не удалось сохранить просмотр", show_alert=True
            )
            return True
        await self._api.answer_callback_query(callback.id, text="Просмотр отмечен")
        if callback.message is None:
            return True
        refreshed = await self._learning.get_available_lesson(
            callback.sender.id, lesson_id
        )
        if refreshed is None:
            return True
        if (
            refreshed.is_current
            and refreshed.viewed_at is None
            and refreshed.materials
            and all(material.is_viewed for material in refreshed.materials)
        ):
            # The last material was just marked: finish the lesson right away
            # instead of asking for one more confirmation button.
            try:
                result = await self._progression.mark_current_viewed(
                    callback.sender.id,
                    expected_lesson_id=lesson_id,
                )
            except (LessonMismatchError, ActiveLessonNotFoundError):
                await self._send_lesson_workspace(callback.message.chat.id, refreshed)
                return True
            completed = await self._learning.get_available_lesson(
                callback.sender.id, lesson_id
            )
            if completed is not None and completed.assignment_instructions:
                await self._send_lesson_workspace(callback.message.chat.id, completed)
            else:
                await self._api.send_message(
                    callback.message.chat.id,
                    self._viewed_result_text(result),
                    parse_mode="HTML",
                    reply_markup=await self._main_keyboard(callback.sender.id),
                )
            return True
        await self._send_lesson_workspace(callback.message.chat.id, refreshed)
        return True

    async def _handle_homework_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False
        try:
            lesson_id = UUID(callback.data.split(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            await self._api.answer_callback_query(callback.id, text="Задание не найдено")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        if (
            lesson is None
            or lesson.assignment_instructions is None
            or callback.message is None
        ):
            await self._api.answer_callback_query(
                callback.id, text="Задание пока недоступно", show_alert=True
            )
            return True
        await self._api.answer_callback_query(callback.id)
        await self._api.send_message(
            callback.message.chat.id,
            self._lesson_homework_text(lesson),
            parse_mode="HTML",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "📥 Начать сдачу",
                            "callback_data": f"submission:{lesson.lesson_id}",
                        },
                        {
                            "text": "❓ Уточнить у куратора",
                            "callback_data": f"ask_curator:{lesson.lesson_id}",
                        },
                    ],
                    [
                        {
                            "text": "← К уроку",
                            "callback_data": f"lesson:open:{lesson.lesson_id}",
                        }
                    ]
                ]
            },
        )
        return True

    async def _handle_submission_start_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or callback.message is None or not callback.data:
            return False
        try:
            lesson_id = UUID(callback.data.split(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            await self._api.answer_callback_query(callback.id, text="Урок не найден")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        if lesson is None or not lesson.is_current:
            await self._api.answer_callback_query(
                callback.id,
                text="Сдать можно только работу текущей недели",
                show_alert=True,
            )
            return True
        await self._api.answer_callback_query(callback.id)
        await self._api.send_message(
            callback.message.chat.id,
            await self._begin_submission(callback.sender.id),
            parse_mode="HTML",
            reply_markup=await self._main_keyboard(callback.sender.id),
        )
        return True

    async def _handle_ask_curator_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or callback.message is None or not callback.data:
            return False
        try:
            lesson_id = UUID(callback.data.split(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            await self._api.answer_callback_query(callback.id, text="Урок не найден")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        if lesson is None or not lesson.is_current:
            await self._api.answer_callback_query(
                callback.id,
                text="Вопрос можно задать только по текущему уроку",
                show_alert=True,
            )
            return True
        try:
            prompt = await self._submissions.begin_question(
                callback.sender.id,
                expected_lesson_id=lesson_id,
            )
        except NoActiveAssignmentError:
            await self._api.answer_callback_query(
                callback.id,
                text="Задание сейчас недоступно",
                show_alert=True,
            )
            return True

        await self._api.answer_callback_query(callback.id)
        await self._api.send_message(
            callback.message.chat.id,
            (
                "❓ <b>ВОПРОС КУРАТОРУ</b>\n\n"
                f"📘 Урок {prompt.lesson_position}: "
                f"{escape(prompt.lesson_title)}\n\n"
                "Напиши вопрос одним сообщением. Я отправлю его кураторам.\n"
                "Для отмены используй /cancel."
            ),
            parse_mode="HTML",
            reply_markup=await self._main_keyboard(callback.sender.id),
        )
        return True

    async def _handle_submission_template_callback(self, update: TelegramUpdate) -> bool:
        callback = update.callback_query
        if callback is None or not callback.data:
            return False
        try:
            lesson_id = UUID(callback.data.split(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            await self._api.answer_callback_query(callback.id, text="Урок не найден")
            return True
        lesson = await self._learning.get_available_lesson(callback.sender.id, lesson_id)
        if lesson is None or callback.message is None:
            await self._api.answer_callback_query(
                callback.id, text="Урок пока недоступен", show_alert=True
            )
            return True
        await self._api.answer_callback_query(callback.id)
        template = (
            "1. КОНТЕКСТ\n"
            "Что происходит на рынке и на каких таймфреймах?\n\n"
            "2. ЛОГИКА\n"
            "Какие DR, SNR, IRL/ERL, Narrative или Entry Model использованы?\n\n"
            "3. ГРАФИЧЕСКИЙ ПРИМЕР\n"
            "Приложи размеченный график или схему.\n\n"
            "4. ВЫВОД\n"
            "Что подтверждает идею и что её инвалидирует?\n\n"
            "5. ВОПРОС КУРАТОРУ\n"
            "Где именно нужна дополнительная проверка?"
        )
        await self._api.send_message(
            callback.message.chat.id,
            f"<b>PROJECT FIX / ANSWER TEMPLATE</b>\n"
            f"{escape(lesson.title)}\n\n"
            "Это рекомендуемая структура — её можно адаптировать под задание.\n\n"
            f"<pre>{escape(template)}</pre>",
            parse_mode="HTML",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "📝 Открыть задание",
                            "callback_data": f"homework:{lesson.lesson_id}",
                        }
                    ],
                    [
                        {
                            "text": "← К уроку",
                            "callback_data": f"lesson:open:{lesson.lesson_id}",
                        }
                    ],
                ]
            },
        )
        return True

    @staticmethod
    def _telegram_lesson_source(lesson: CurrentLesson) -> tuple[int, int] | None:
        if lesson.video_source.value != "telegram_channel" or not lesson.video_reference:
            return None
        chat_id, separator, message_id = lesson.video_reference.strip().partition(":")
        if not separator:
            return None
        try:
            parsed_chat_id = int(chat_id)
            parsed_message_id = int(message_id)
        except ValueError:
            return None
        if parsed_message_id <= 0:
            return None
        return parsed_chat_id, parsed_message_id

    async def _begin_submission(self, telegram_user_id: int) -> str:
        try:
            prompt = await self._submissions.begin(telegram_user_id)
        except NoActiveAssignmentError:
            return "🔒 <b>Нет доступного задания</b>\n\nСначала открой текущий урок."
        except SubmissionPendingError:
            return "⏳ <b>ДЗ уже отправлено</b>\n\nРабота ожидает проверки куратора."
        except AssignmentAcceptedError:
            return "✅ <b>Это ДЗ уже принято</b>\n\nПовторная отправка не требуется."
        except LessonNotViewedError:
            return (
                "👀 <b>Сначала отметь просмотр материалов</b>\n\n"
                "Открой «📘 Текущий урок», посмотри материалы и нажми "
                "«✅ Я посмотрел все материалы»."
            )
        return self._submission_prompt_text(prompt)

    @staticmethod
    def _lesson_reply_markup(lesson: CurrentLesson) -> dict[str, object]:
        rows: list[list[dict[str, object]]] = []
        if lesson.video_source.value == "external_url" and lesson.video_reference:
            rows.append(
                [
                    {
                        "text": "▶ Смотреть урок",
                        "url": vimeo_watch_url(lesson.video_reference),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "✅ Я посмотрел материал",
                    "callback_data": f"lesson:viewed:{lesson.lesson_id}",
                }
            ]
        )
        return {
            "inline_keyboard": rows
        }

    @staticmethod
    def _completed_lesson_reply_markup(lesson: CurrentLesson) -> dict[str, object]:
        """Keep rewatch and homework entry points once the view is confirmed."""
        rows: list[list[dict[str, object]]] = []
        if lesson.video_source.value == "external_url" and lesson.video_reference:
            rows.append(
                [
                    {
                        "text": "▶ Смотреть урок повторно",
                        "url": vimeo_watch_url(lesson.video_reference),
                    }
                ]
            )
        for material in lesson.materials:
            rows.append(
                [
                    {
                        "text": (
                            f"{'🖼' if material.kind == 'image' else '▶️'} "
                            f"{material.position}. {material.title}"
                        )[:64],
                        "callback_data": (
                            f"material:{lesson.lesson_id}:{material.position}"
                        ),
                    }
                ]
            )
        if lesson.assignment_instructions:
            rows.append(
                [
                    {
                        "text": "📝 Домашнее задание",
                        "callback_data": f"homework:{lesson.lesson_id}",
                    }
                ]
            )
        return {"inline_keyboard": rows}

    @staticmethod
    def _replay_lesson_reply_markup(lesson: CurrentLesson) -> dict[str, object]:
        rows: list[list[dict[str, object]]] = []
        if lesson.video_source.value == "external_url" and lesson.video_reference:
            rows.append(
                [
                    {
                        "text": "▶ Смотреть урок повторно",
                        "url": vimeo_watch_url(lesson.video_reference),
                    }
                ]
            )
        return {"inline_keyboard": rows}

    @staticmethod
    def _lesson_catalog_text(outline: CourseOutline | None) -> str:
        if outline is None:
            return "📚 <b>Курс пока не назначен</b>"
        return (
            f"📚 <b>{escape(outline.title)}</b>\n\n"
            "Выбери текущий или уже пройденный урок. Будущие уроки откроются "
            "по мере прохождения программы."
        )

    @staticmethod
    def _lesson_catalog_reply_markup(outline: CourseOutline) -> dict[str, object]:
        rows: list[list[dict[str, object]]] = []
        for lesson in outline.lessons:
            if lesson.is_current:
                icon = "▶"
            elif lesson.is_available:
                icon = "✅"
            else:
                icon = "🔒"
            action = "open" if lesson.is_available else "locked"
            rows.append(
                [
                    {
                        "text": f"{icon} {lesson.position}. {lesson.title}"[:64],
                        "callback_data": f"lesson:{action}:{lesson.lesson_id}",
                    }
                ]
            )
        return {"inline_keyboard": rows}

    @staticmethod
    def _viewed_result_text(result: ProgressionResult) -> str:
        if result.course_completed:
            return (
                "🏆 <b>УРОК ПРОЙДЕН</b>\n\n"
                "Это был последний урок курса. Все материалы завершены!"
            )
        if result.current_lesson_position != result.lesson_position:
            if result.next_lesson_available:
                return (
                    "✅ <b>УРОК ПРОЙДЕН</b>\n\n"
                    f"Открыт урок {result.current_lesson_position}. "
                    "Нажми «📘 Текущий урок», чтобы продолжить."
                )
            return (
                "✅ <b>УРОК ПРОЙДЕН</b>\n\n"
                "Следующий урок откроется по расписанию."
            )
        return (
            "✅ <b>МАТЕРИАЛЫ ОТМЕЧЕНЫ</b>\n\n"
            "Если в уроке есть ДЗ — открой его в карточке урока. "
            "Если ДЗ нет — переходи к следующему доступному уроку."
        )

    async def _accept_text_submission(self, telegram_user_id: int, text: str) -> str:
        try:
            question = await self._submissions.submit_question_text(telegram_user_id, text)
        except NotAwaitingQuestionError:
            pass
        except EmptySubmissionError:
            return "⚠️ Вопрос пустой. Напиши вопрос одним сообщением."
        else:
            await self._notify_curators_about_question(question)
            return (
                "✅ <b>Вопрос отправлен куратору</b>\n\n"
                "Куратор увидит вопрос в Telegram и сможет ответить тебе лично."
            )

        try:
            receipt = await self._submissions.submit_text(telegram_user_id, text)
        except NotAwaitingSubmissionError:
            return await self._accept_revision_text(telegram_user_id, text)
        except EmptySubmissionError:
            return "⚠️ Ответ пустой. Пришли текст домашнего задания одним сообщением."
        except UnsupportedSubmissionKindError:
            return "📎 Для этого задания требуется другой формат ответа."

        return self._submission_receipt_text(receipt)

    async def _accept_autostart_attachment(
        self,
        telegram_user_id: int,
        attachment: HomeworkAttachment,
        caption: str | None,
    ) -> str:
        """A student sends the answer file without pressing the submit button."""
        try:
            await self._submissions.begin(telegram_user_id)
        except SubmissionWorkflowError:
            return self._unknown_command_text()
        try:
            receipt = await self._submissions.submit_attachment(
                telegram_user_id,
                attachment,
                caption=caption,
            )
        except UnsupportedSubmissionKindError:
            return (
                "⚠️ <b>Неверный формат</b>\n\n"
                "Для этого задания нужен другой тип ответа. "
                "Режим сдачи остаётся активным."
            )
        except SubmissionWorkflowError:
            return self._unknown_command_text()
        return self._submission_receipt_text(receipt)

    async def _accept_revision_text(self, telegram_user_id: int, text: str) -> str:
        """A student on revision writes the fixed answer without pressing the button."""
        journey = await self._students.get_journey(telegram_user_id)
        if journey is None or journey.stage is not StudentStage.REVISION_REQUESTED:
            return self._unknown_command_text()
        try:
            await self._submissions.begin(telegram_user_id)
            receipt = await self._submissions.submit_text(telegram_user_id, text)
        except SubmissionWorkflowError:
            return self._unknown_command_text()
        return self._submission_receipt_text(receipt)

    async def _notify_curators_about_question(
        self,
        question: CuratorQuestionReceipt,
    ) -> None:
        if not question.curator_telegram_user_ids:
            return
        text = self._curator_question_text(question)
        for curator_id in question.curator_telegram_user_ids:
            try:
                await self._api.send_message(
                    curator_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=curator_keyboard(),
                )
            except (TelegramAPIError, TelegramTransportError):
                continue

    @staticmethod
    def _feedback_attachment_from_message(
        message: TelegramMessage,
    ) -> FeedbackAttachmentInput | None:
        if message.document is not None:
            return FeedbackAttachmentInput(
                kind=AttachmentKind.DOCUMENT,
                telegram_file_id=message.document.file_id,
                telegram_file_unique_id=message.document.file_unique_id,
                file_name=message.document.file_name,
                mime_type=message.document.mime_type,
                file_size=message.document.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
            )
        if message.video is not None:
            return FeedbackAttachmentInput(
                kind=AttachmentKind.VIDEO,
                telegram_file_id=message.video.file_id,
                telegram_file_unique_id=message.video.file_unique_id,
                file_name=message.video.file_name,
                mime_type=message.video.mime_type or "video/mp4",
                file_size=message.video.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                duration_seconds=message.video.duration,
                width=message.video.width,
                height=message.video.height,
            )
        if message.video_note is not None:
            return FeedbackAttachmentInput(
                kind=AttachmentKind.VIDEO_NOTE,
                telegram_file_id=message.video_note.file_id,
                telegram_file_unique_id=message.video_note.file_unique_id,
                mime_type="video/mp4",
                file_size=message.video_note.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                duration_seconds=message.video_note.duration,
                width=message.video_note.length,
                height=message.video_note.length,
            )
        if message.photo:
            photo = max(
                message.photo,
                key=lambda item: item.file_size or item.width * item.height,
            )
            return FeedbackAttachmentInput(
                kind=AttachmentKind.PHOTO,
                telegram_file_id=photo.file_id,
                telegram_file_unique_id=photo.file_unique_id,
                file_size=photo.file_size,
                mime_type="image/jpeg",
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                width=photo.width,
                height=photo.height,
            )
        return None

    async def _accept_attachment_submission(
        self,
        telegram_user_id: int,
        message: TelegramMessage,
    ) -> str:
        if message.document is not None:
            attachment = HomeworkAttachment(
                kind=AttachmentKind.DOCUMENT,
                telegram_file_id=message.document.file_id,
                telegram_file_unique_id=message.document.file_unique_id,
                file_name=message.document.file_name,
                mime_type=message.document.mime_type,
                file_size=message.document.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
            )
        elif message.video is not None:
            attachment = HomeworkAttachment(
                kind=AttachmentKind.VIDEO,
                telegram_file_id=message.video.file_id,
                telegram_file_unique_id=message.video.file_unique_id,
                file_name=message.video.file_name,
                mime_type=message.video.mime_type or "video/mp4",
                file_size=message.video.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                duration_seconds=message.video.duration,
                width=message.video.width,
                height=message.video.height,
            )
        elif message.video_note is not None:
            attachment = HomeworkAttachment(
                kind=AttachmentKind.VIDEO_NOTE,
                telegram_file_id=message.video_note.file_id,
                telegram_file_unique_id=message.video_note.file_unique_id,
                mime_type="video/mp4",
                file_size=message.video_note.file_size,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                duration_seconds=message.video_note.duration,
                width=message.video_note.length,
                height=message.video_note.length,
            )
        else:
            photo = max(
                message.photo,
                key=lambda item: item.file_size or item.width * item.height,
            )
            attachment = HomeworkAttachment(
                kind=AttachmentKind.PHOTO,
                telegram_file_id=photo.file_id,
                telegram_file_unique_id=photo.file_unique_id,
                file_size=photo.file_size,
                mime_type="image/jpeg",
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                width=photo.width,
                height=photo.height,
            )

        try:
            receipt = await self._submissions.submit_attachment(
                telegram_user_id,
                attachment,
                caption=message.caption,
            )
        except NotAwaitingSubmissionError:
            # Albums arrive as separate messages: the first one completes the
            # submission, the rest should join it instead of confusing the bot.
            try:
                appended = await self._submissions.append_attachment(
                    telegram_user_id,
                    attachment,
                    caption=message.caption,
                )
            except NoPendingSubmissionError:
                return await self._accept_autostart_attachment(
                    telegram_user_id,
                    attachment,
                    message.caption,
                )
            return (
                "📎 <b>Файл добавлен к отправленной работе</b>\n\n"
                f"📘 Урок {appended.lesson_position}: "
                f"{escape(appended.lesson_title)}\n"
                f"🔁 Попытка: {appended.attempt_number}\n"
                f"Вложений в работе: <b>{appended.attachment_count}</b>"
            )
        except UnsupportedSubmissionKindError:
            return (
                "⚠️ <b>Неверный формат</b>\n\n"
                "Для этого задания нужен другой тип ответа. "
                "Режим сдачи остаётся активным."
            )

        return self._submission_receipt_text(receipt)

    @staticmethod
    def _submission_prompt_text(prompt: SubmissionPrompt) -> str:
        format_hints = {
            SubmissionKind.TEXT: "Текстовый ответ одним сообщением или ссылка на Notion.",
            SubmissionKind.FILE: "Один файл с выполненной работой.",
            SubmissionKind.PHOTO: "Одна фотография с выполненной работой.",
            SubmissionKind.VIDEO: "Видеофайл или видеосообщение.",
            SubmissionKind.ANY: (
                "Текст, ссылка на Notion, файл, фотография или видео."
            ),
        }
        return (
            "📤 <b>СДАЧА ДОМАШНЕГО ЗАДАНИЯ</b>\n\n"
            f"📘 <b>Урок {prompt.lesson_position}: {escape(prompt.lesson_title)}</b>\n\n"
            "📝 <b>Что нужно сделать:</b>\n"
            f"{escape(prompt.instructions)}\n\n"
            "📎 <b>Как отправить ответ:</b>\n"
            f"{format_hints[prompt.submission_kind]}\n\n"
            "Можно прислать ссылку на Notion, если работа оформлена там.\n"
            "Для отмены используй /cancel."
        )

    @staticmethod
    def _curator_question_text(question: CuratorQuestionReceipt) -> str:
        username = (
            f"@{escape(question.student_username)}"
            if question.student_username
            else "username не указан"
        )
        return (
            "❓ <b>ВОПРОС ОТ УЧЕНИКА</b>\n\n"
            f"👤 <b>{escape(question.student_name)}</b> · {username}\n"
            f"📚 Курс: <b>{escape(question.course_title)}</b>\n"
            f"📘 Урок {question.lesson_position}: "
            f"<b>{escape(question.lesson_title)}</b>\n\n"
            "💬 <b>Вопрос:</b>\n"
            f"{escape(question.question_text)}"
        )

    @staticmethod
    def _submission_receipt_text(receipt: SubmissionReceipt) -> str:
        return (
            "✅ <b>ДОМАШНЕЕ ЗАДАНИЕ ОТПРАВЛЕНО</b>\n\n"
            f"📘 Урок {receipt.lesson_position}: {escape(receipt.lesson_title)}\n"
            f"🔁 Попытка: {receipt.attempt_number}\n"
            "⏳ Статус: <b>на проверке</b>\n\n"
            "После проверки здесь появится результат куратора."
        )

    @staticmethod
    def _unknown_command_text() -> str:
        return (
            "🤔 <b>Не понял сообщение</b>\n\n"
            "Используй кнопки внизу или команды /start, /lesson и /progress."
        )
