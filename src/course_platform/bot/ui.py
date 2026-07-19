"""Reusable Telegram keyboard and notification message formatting."""

from html import escape

from course_platform.models.enums import FeedbackVerdict
from course_platform.services.notifications import AccessNotification, FeedbackNotification
from course_platform.services.students import StudentJourney, StudentStage


def main_keyboard(
    journey: StudentJourney | None,
    *,
    is_reviewer: bool = False,
) -> dict[str, object]:
    stage = journey.stage if journey is not None else StudentStage.NO_COURSE
    return stage_keyboard(stage, is_reviewer=is_reviewer)


def stage_keyboard(
    stage: StudentStage,
    *,
    is_reviewer: bool = False,
) -> dict[str, object]:
    if stage is StudentStage.COURSE_COMPLETED:
        rows = [
            [{"text": "🏆 Итоги курса"}, {"text": "📚 База материалов"}],
            [{"text": "🎯 Pre session + Backtest"}],
        ]
    elif stage is StudentStage.AWAITING_REVIEW:
        rows = [[{"text": "⏳ Статус ДЗ"}, {"text": "📘 Текущий урок"}]]
    elif stage is StudentStage.REVISION_REQUESTED:
        rows = [[{"text": "🔄 Отправить доработку"}, {"text": "📘 Текущий урок"}]]
    elif stage is StudentStage.READY_TO_SUBMIT:
        rows = [[{"text": "📥 Сдать ДЗ"}, {"text": "📘 Текущий урок"}]]
    else:
        rows = [[{"text": "📘 Текущий урок"}, {"text": "📊 Мой прогресс"}]]

    rows.append([{"text": "📚 Программа курса"}, {"text": "🗂 Мои разборы"}])
    rows.append([{"text": "⚙️ Настройки"}, {"text": "ℹ️ Помощь"}])
    if is_reviewer:
        rows.append([{"text": "Режим куратора"}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "input_field_placeholder": "PROJECT FIX · выбери действие",
    }


BOT_KEYBOARD = main_keyboard(None)


def curator_keyboard() -> dict[str, object]:
    return {
        "keyboard": [
            [{"text": "🎓 Выдать доступ"}],
            [{"text": "🎬 Видео уроков"}],
            [{"text": "📥 Очередь проверки"}, {"text": "🗂 Проверенные"}],
            [{"text": "📊 Сводка куратора"}, {"text": "👥 Ученики"}],
            [{"text": "🎓 Режим ученика"}],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "Выбери действие куратора",
    }


def feedback_notification_text(notification: FeedbackNotification) -> str:
    if notification.verdict is FeedbackVerdict.REVISION_REQUESTED:
        return (
            "🔄 <b>ДЗ нужно доработать</b>\n\n"
            f"Комментарий куратора:\n{escape(notification.message)}\n\n"
            "Исправь работу и просто пришли новую версию сообщением — "
            "текстом, файлом, фото или видео."
        )
    if notification.course_completed:
        return (
            "🏆 <b>ДЗ принято</b>\n\n"
            f"Комментарий куратора:\n{escape(notification.message)}\n\n"
            "Курс завершён. Все обязательные уроки пройдены."
        )
    return (
        "✅ <b>ДЗ принято</b>\n\n"
        f"Комментарий куратора:\n{escape(notification.message)}\n\n"
        f"Открыт урок {notification.current_lesson_position}. "
        "Нажми «📘 Текущий урок», чтобы продолжить обучение."
    )


def access_notification_text(notification: AccessNotification) -> str:
    return (
        "✅ <b>Доступ к курсу открыт</b>\n\n"
        f"Курс: <b>{escape(notification.course_title)}</b>\n"
        f"Стартовый урок: <b>{notification.current_lesson_position}</b>\n\n"
        "Нажми «📘 Текущий урок», чтобы начать обучение. "
        "Внутри урока будут материалы, статус просмотра и кнопка сдачи ДЗ, если задание есть."
    )
