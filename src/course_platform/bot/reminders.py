"""Telegram delivery for durable lesson reminders."""

import logging
from html import escape

from course_platform.bot.api import TelegramBotClient
from course_platform.bot.ui import curator_keyboard, stage_keyboard
from course_platform.models.enums import ReminderKind
from course_platform.services.reminders import LessonReminderService, ReminderDelivery
from course_platform.services.students import StudentStage

logger = logging.getLogger(__name__)


class TelegramLessonReminderDispatcher:
    def __init__(
        self,
        api: TelegramBotClient,
        reminders: LessonReminderService,
    ) -> None:
        self._api = api
        self._reminders = reminders

    async def dispatch_due(self) -> int:
        due = await self._reminders.list_due()
        sent_count = 0
        for reminder in due:
            try:
                text = reminder_text(reminder)
                reply_markup = (
                    curator_keyboard()
                    if reminder.kind is ReminderKind.CURATOR_ALERT
                    else stage_keyboard(StudentStage.NEEDS_VIEW)
                )
                for recipient_id in reminder.recipient_telegram_ids:
                    await self._api.send_message(
                        recipient_id,
                        text,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
            except Exception as error:
                logger.exception("Failed to deliver lesson reminder %s", reminder.reminder_id)
                await self._reminders.mark_failed(
                    reminder.reminder_id,
                    type(error).__name__,
                )
                continue

            await self._reminders.mark_sent(reminder.reminder_id)
            sent_count += 1
        return sent_count


def reminder_text(reminder: ReminderDelivery) -> str:
    if reminder.kind is ReminderKind.CURATOR_ALERT:
        username = f"@{escape(reminder.student_username)}" if reminder.student_username else "—"
        return (
            "⚠️ <b>УЧЕНИКУ НУЖНО ВНИМАНИЕ</b>\n\n"
            f"👤 {escape(reminder.student_name)} ({username})\n"
            f"🎓 {escape(reminder.course_title)}\n"
            f"📘 Урок {reminder.lesson_position}: {escape(reminder.lesson_title)}\n"
            f"🕒 Последняя активность: {reminder.last_activity_at:%d.%m.%Y %H:%M}\n\n"
            "Ученик не отметил просмотр после серии напоминаний."
        )

    try:
        message = reminder.message_text.format(
            lesson_title=reminder.lesson_title,
            course_title=reminder.course_title,
            student_name=reminder.student_name,
        )
    except (KeyError, ValueError):
        message = reminder.message_text
    tone = (
        "🔔 <b>НАПОМИНАНИЕ ОБ УРОКЕ</b>"
        if reminder.kind is ReminderKind.STUDENT_GENTLE
        else "📚 <b>ПРОДОЛЖИМ ОБУЧЕНИЕ?</b>"
    )
    return (
        f"{tone}\n\n"
        f"{escape(message)}\n\n"
        "Нажми «📘 Текущий урок», чтобы вернуться к материалу."
    )
