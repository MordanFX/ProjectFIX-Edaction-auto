"""Update the local demonstration course with the PRACTICE 2026 outline."""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory, session_scope
from course_platform.models import Assignment, Course, Lesson, LessonMaterial
from course_platform.models.enums import SubmissionKind, VideoSource

COURSE_SLUG = "demo-learning-course"
COURSE_TITLE = "PRACTICE 2026 v2.0"
COURSE_DESCRIPTION = (
    "Практическая программа по анализу рынка, построению торгового сценария "
    "и системной работе над результатами."
)
WELCOME_VIDEO_URL = "https://vimeo.com/1196958528?share=copy&fl=sv&fe=ci"
WEEK_1_VIDEO_URL = "https://vimeo.com/1197792122?share=copy&fl=sv&fe=ci"
WEEK_2_VIDEO_URL = "https://vimeo.com/1199048884?share=copy&fl=sv&fe=ci"
WEEK_3_VIDEO_URL = "https://vimeo.com/1201863019?share=copy&fl=sv&fe=ci"
WEEK_4_VIDEO_URL = "https://vimeo.com/1203908424?share=copy&fl=sv&fe=ci"
WEEK_5_VIDEO_URL = "https://vimeo.com/1205876894?share=copy&fl=sv&fe=ci"
WEEK_1_MATERIALS = (
    ("Market Logic · Запись стрима", WEEK_1_VIDEO_URL, None),
    (
        "QnA with Vlad · 04.06",
        "https://vimeo.com/1198445213?share=copy&fl=sv&fe=ci",
        "Разбор механики рынка на графике GBP, определение расширения, боковика и "
        "флэта, примеры на чарте и другие вопросы из чата.",
    ),
)
WEEK_2_MATERIALS = (
    (
        "Liq. Point & Narrative · Запись стрима",
        WEEK_2_VIDEO_URL,
        "Liquidity Point, роль narrative, рыночная логика, расположение ликвидности "
        "и влияние контекста на дальнейшее движение цены.",
    ),
    (
        "Обсуждаем ещё раз Narrative · 08.06",
        "https://vimeo.com/1199453680?fl=ip&fe=ec",
        None,
    ),
    (
        "Fast QnA · Разница между Narrative и Context · 09.06",
        "https://vimeo.com/1199764991?share=copy&fl=sv&fe=ci",
        None,
    ),
    (
        "Storyline & Reversal · Запись стрима · 09.06",
        "https://vimeo.com/1199846875?share=copy&fl=sv&fe=ci",
        None,
    ),
    (
        "QnA with Vlad · SNR и диапазоны · 13.06",
        "https://vimeo.com/1201048545?share=copy&fl=sv&fe=ci",
        "Нехватка RR при входе от SNR, формирование второй границы DR, разборы "
        "примеров практикантов и другие вопросы из чата.",
    ),
    (
        "Учимся повторно определять контекст · 15.06",
        "https://vimeo.com/1201456952?share=copy&fl=sv&fe=ci",
        "Повторное определение контекста и разбор практических примеров.",
    ),
)
WEEK_3_MATERIALS = (
    ("Delivery A-B. Part 1 · 16.06", WEEK_3_VIDEO_URL, None),
    (
        "QnA with Vlad · Диапазоны, SNR, IRL · 18.06",
        "https://vimeo.com/1202561289?share=copy&fl=sv&fe=ci",
        "Расширение DR, SNR и поглощение DR, таргетирование, формирование DR без "
        "поглощения, X/X-1 IRL в Premium/Discount и увеличение насмотренности. "
        "На последних 10 минутах дано дополнительное задание.",
    ),
    (
        "Delivery A-B. Part 2 · 20.06",
        "https://vimeo.com/1203039763?share=copy&fl=sv&fe=ci",
        None,
    ),
    (
        "Fast QnA with Vlad · DR и его формирование · 22.06",
        "https://vimeo.com/1203472991?share=copy&fl=sv&fe=ci",
        None,
    ),
)
WEEK_4_MATERIALS = (
    (
        "Delivery A-B. Part 3 · 23.06",
        WEEK_4_VIDEO_URL,
        "Типы коррекций, монетизация идей после каждой из них, визуально-объёмный "
        "анализ, сила и слабость, формирование фракталов и невозможность движения.",
    ),
    (
        "TA, FTA + QnA with Vlad · 25.06",
        "https://vimeo.com/1204591760?share=copy&fl=sv&fe=ci",
        "Target Area и First Trouble Area: валидация, инвалидация и монетизация "
        "идей после прихода цены в целевую область.",
    ),
    (
        "Разбираем графики, ищем тренды · 27.06",
        "https://vimeo.com/1205072178?share=copy&fl=sv&fe=ci",
        "Совместный разбор трендов на графиках. Задание из этого материала будет "
        "проверяться вместе на отдельном стриме.",
    ),
)
WEEK_4_IMAGES = (
    (
        "Пример из лекции · Формирование Order Flow",
        "frontend/public/course-assets/week4-example-1.png",
        "Размеченный пример GBPUSD: диапазоны, SNR, внутренняя ликвидность и "
        "формирование следующей волны Order Flow.",
    ),
    (
        "Пример из лекции · Валидация торговой идеи",
        "frontend/public/course-assets/week4-example-2.png",
        "Расширенный пример GBPUSD: Premium/Discount, реакция в TA, слабость "
        "покупателей и подтверждение сценария.",
    ),
)
WEEK_5_MATERIALS = (
    (
        "Entry Models · 30.06",
        WEEK_5_VIDEO_URL,
        "Основные Entry Models, их структура и логика формирования, качественные "
        "точки входа, контекст рынка и модели внутри общей рыночной структуры.",
    ),
    (
        "QnA with Vlad · 02.07",
        "https://vimeo.com/1206544520?share=copy&fl=sv&fe=ci",
        "SOF X-1 и старший диапазон, валидация через OF, формирование SNR, SNR без "
        "диапазона, IRL в расширении и коррекции, Strong Point в TOF и разбор OF "
        "по GBP.",
    ),
    (
        "Risk Management и работа с чартом · 04.07",
        "https://vimeo.com/1206965306?share=copy&fl=sv&fe=ci",
        "Риск-менеджмент, теория вероятности, торговая система и практические "
        "приёмы работы с графиком.",
    ),
)
LESSON_MATERIALS = {
    2: WEEK_1_MATERIALS,
    3: WEEK_2_MATERIALS,
    4: WEEK_3_MATERIALS,
    5: WEEK_4_MATERIALS,
    6: WEEK_5_MATERIALS,
}
LESSON_IMAGES = {5: WEEK_4_IMAGES}

LESSONS = (
    (
        "Welcome · Знакомство",
        "Встреча с участниками практикума.\n"
        "Объяснение плана действий и дальнейшей работы.",
        None,
    ),
    (
        "Education · Week 1",
        "Объяснение ценообразования на рынке и структуры работы с рынком.",
        "1. Описать, что такое классический аукцион и двойной рыночный аукцион.\n"
        "2. Что такое закон спроса и предложения?\n"
        "3. Описать взаимодействие покупателей и продавцов. Что происходит "
        "по завышенной и заниженной цене?\n"
        "4. Какова механика рыночного процесса? Что такое расширение, коррекция и флет?\n\n"
        "К каждому вопросу требуется текстовое описание и схема с графическим "
        "описанием вопроса.",
    ),
    (
        "Education · Week 2 · Liq. Point & Narrative",
        "Разберём понятие Liquidity Point и роль narrative в движении цены. "
        "Поговорим о том, как формируется рыночная логика, где находится "
        "ликвидность и каким образом контекст влияет на дальнейшее развитие движения.\n\n"
        "Storyline & Reversal: повторно учимся определять контекст и разбираем "
        "практические примеры.\n\n"
        "Темы, затронутые на стриме:\n"
        "• нехватка RR при входе от SNR;\n"
        "• формирование второй границы ДР;\n"
        "• разборы примеров практикантов.",
        "БЛОК 1 · Instruments | Logic\n\n"
        "• Описать, что такое Fractal Points. Привести примеры Fractal Points на графике.\n"
        "• Описать, что такое FVG. Какую функцию выполняет FVG на графике?\n\n"
        "БЛОК 1 · TDA | Narrative | Storyline\n\n"
        "• Описать, что такое Top Down Analysis, какие временные периоды используются "
        "и какова последовательность их синхронизации.\n"
        "• Описать, что такое Context на чарте и как его определять.\n"
        "• Что такое торговая идея? Как формировать Narrative? Привести примеры на чарте.\n\n"
        "БЛОК 2 · Instruments | Logic\n\n"
        "• SNR like VC: техническая часть и логика формирования с точки зрения AMT.\n"
        "• Диапазоны. Зоны ключевых покупателей и продавцов.\n\n"
        "БЛОК 2 · TDA | Narrative | Storyline\n\n"
        "• Работа в контексте с помощью Narrative + SNR [VC]: теория и графический пример.\n"
        "• Описать резистивность, слабость и закругление цены; привести примеры "
        "для каждого понятия.\n\n"
        "ДОПОЛНИТЕЛЬНОЕ ЗАДАНИЕ\n\n"
        "Найти 3 ситуации Reversal Trade и полностью описать план трейда с "
        "контекстом и логикой нарратива.",
    ),
    (
        "Education · Week 3 · Delivery A-B. Part 1 & 2",
        "Part 1: DR — что это такое и как используется. Зоны Premium & Discount: "
        "что происходит в этих зонах и как это можно использовать. Расширение и "
        "коррекция диапазонов.\n\n"
        "Part 2: OF / SOF / TOF — способы доставки цены и работа внутри них. "
        "Triggers & Shifted POI как локальная работа в OF. Работа в Continuation "
        "и Retracement, особенности и правила.\n\n"
        "Неделя включает два основных занятия и два дополнительных QnA-разбора.",
        "БЛОК 1 · DELIVERY A-B. PART 1\n\n"
        "• Кто такие ключевые продавцы и покупатели? Что они делают с точки зрения "
        "ценообразования и чем отличаются от обычных продавцов и покупателей?\n"
        "• Что такое DR?\n"
        "• Что такое IRL / ERL?\n"
        "• Чем IRL, сформированные во время расширения диапазона, отличаются от IRL, "
        "сформированных во время его коррекции?\n"
        "• Что такое Premium / Discount и 0,5 DR? Что происходит с ценой в зонах "
        "до и после уровня 0,5?\n"
        "• Как и за счёт чего расширяется и корректируется диапазон?\n\n"
        "БЛОК 2 · DELIVERY A-B. PART 2\n\n"
        "• Что такое OF / SOF / TOF? Привести примеры работы внутри них.\n"
        "• Что такое Triggers & Shifted POI? Привести примеры работы внутри них.\n"
        "• Что такое Continuation Trades? Какие варианты монетизации бывают?\n"
        "• Что такое Retracement Trades? Какие варианты монетизации бывают?\n\n"
        "К каждому вопросу требуется текстовое описание и схема с графическим "
        "описанием вопроса.",
    ),
    (
        "Education · Week 4 · Delivery A-B. Part 3",
        "Типы коррекций и ожидания после каждой из них для монетизации идей. "
        "Визуально-объёмный анализ: сила и слабость, формирование фракталов, "
        "невозможность движения, связь времени и цены.\n\n"
        "Дополнительные материалы: два размеченных примера из лекции на GBPUSD.",
        "БЛОК 1 · DELIVERY A-B. PART 3\n\n"
        "1. Какие бывают типы коррекций? Как монетизировать идеи после той или "
        "иной коррекции?\n"
        "2. Что такое объёмно-визуальный анализ? Как его использовать и какие "
        "преимущества он даёт?\n"
        "3. О чём говорит формирование фрактала при расширении диапазона и как "
        "это использовать?\n"
        "4. О чём говорит формирование фрактала при коррекции диапазона и как "
        "это использовать?\n"
        "5. Какие условия при коррекции должны выполняться для входа в позицию?\n"
        "6. О чём говорит отсутствие опорных областей при коррекции диапазона? "
        "Какое преимущество это даёт?\n"
        "7. Моментум цены: как время связано с ценой и какое преимущество это даёт?\n"
        "8. О чём говорит формирование опорных областей при расширении диапазона? "
        "Какое преимущество это даёт?\n\n"
        "БЛОК 2 · TA / FTA\n\n"
        "Что такое TA? Как валидировать и инвалидировать TA? Как монетизировать "
        "идеи после прихода цены в TA?\n\n"
        "КОЛЛЕКТИВНЫЙ РАЗБОР · ОТПРАВЛЯТЬ НА ПРОВЕРКУ НЕ НУЖНО\n\n"
        "Разобрать тренд GBPUSD с 20 ноября 2025 года по 6 января. Проверка этого "
        "задания пройдёт совместно на отдельном стриме.",
    ),
    (
        "Education · Week 5 · Entry Models & Risk Management",
        "Основные Entry Models, их структура и логика формирования. Определение "
        "качественных точек входа с учётом контекста и общей рыночной структуры.\n\n"
        "QnA-конференция закрывает вопросы текущего этапа. Финальный блок недели "
        "посвящён риск-менеджменту, торговой системе и работе с чартом.",
        "БЛОК 1 · EXECUTION | MANAGEMENT\n\n"
        "Описать следующие модели входа:\n"
        "• Reversal Trade;\n"
        "• Continuation Trade;\n"
        "• Retracement Trade;\n"
        "• Invalidation TA;\n"
        "• Flat / Range.\n\n"
        "К каждой модели добавить схему и пример.\n\n"
        "БЛОК 2 · RISK MANAGEMENT SYSTEM\n\n"
        "• Описать риск-менеджмент: риск на сделку, лимит сделок, дневной убыток, "
        "таргетирование R:R и работу с несколькими активами.\n"
        "• Изучить таблицу с теорией вероятности. Сначала создать собственную копию "
        "через «Файл → Создать копию». Описать ожидаемый WinRate и возможные "
        "просадки, а также правила адаптации и возврата риска.\n"
        "• Привести в порядок торговую систему и закрыть все незавершённые пункты.\n"
        "• Прислать готовую торговую систему на проверку.\n\n"
        "ТАБЛИЦА РИСК-МЕНЕДЖМЕНТА\n"
        "https://docs.google.com/spreadsheets/d/1Bn2vcxMvtOc7KQEuUDFTKLfFf60UL03B67Zj_hbLzmA/edit?gid=0#gid=0\n\n"
        "ДЕДЛАЙН: ПЯТНИЦА, 10.07",
    ),
    ("Q&A · Ответы на вопросы", "Разбор вопросов по материалам программы.", None),
    ("Practice · Pre session", "Построение утренних планов.", None),
    ("Practice · Post session", "Анализ графика постфактум.", None),
    ("Practice · Weekly performance review", "Анализ прошедшей недели.", None),
)


async def update_practice_course() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise SystemExit("Local course content update is disabled in production")

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_scope(session_factory) as session:
            course = await session.scalar(
                select(Course)
                .options(
                    selectinload(Course.lessons).selectinload(Lesson.assignment),
                    selectinload(Course.lessons).selectinload(Lesson.materials),
                )
                .where(Course.slug == COURSE_SLUG)
            )
            if course is None:
                raise RuntimeError(f"Course {COURSE_SLUG!r} was not found")

            course.title = COURSE_TITLE
            course.description = COURSE_DESCRIPTION
            by_position = {lesson.position: lesson for lesson in course.lessons}

            for position, (title, description, homework) in enumerate(LESSONS, start=1):
                lesson = by_position.get(position)
                if lesson is None:
                    lesson = Lesson(
                        course_id=course.id,
                        position=position,
                        video_source=VideoSource.PLACEHOLDER,
                        requires_view_confirmation=True,
                    )
                    session.add(lesson)
                lesson.title = title
                lesson.description = description
                lesson.is_published = True
                if position == 1:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WELCOME_VIDEO_URL
                elif position == 2:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WEEK_1_VIDEO_URL
                elif position == 3:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WEEK_2_VIDEO_URL
                elif position == 4:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WEEK_3_VIDEO_URL
                elif position == 5:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WEEK_4_VIDEO_URL
                elif position == 6:
                    lesson.video_source = VideoSource.EXTERNAL_URL
                    lesson.video_reference = WEEK_5_VIDEO_URL
                if position in LESSON_MATERIALS:
                    existing_materials = {
                        material.position: material for material in lesson.materials
                    }
                    active_positions: set[int] = set()
                    for material_position, (title, url, description) in enumerate(
                        LESSON_MATERIALS[position], start=1
                    ):
                        active_positions.add(material_position)
                        material = existing_materials.get(material_position)
                        if material is None:
                            material = LessonMaterial(position=material_position)
                            lesson.materials.append(material)
                        material.title = title
                        material.description = description
                        material.kind = "video"
                        material.video_source = VideoSource.EXTERNAL_URL
                        material.video_reference = url
                    for image_position, (title, reference, description) in enumerate(
                        LESSON_IMAGES.get(position, ()),
                        start=len(LESSON_MATERIALS[position]) + 1,
                    ):
                        active_positions.add(image_position)
                        material = existing_materials.get(image_position)
                        if material is None:
                            material = LessonMaterial(position=image_position)
                            lesson.materials.append(material)
                        material.title = title
                        material.description = description
                        material.kind = "image"
                        material.video_source = VideoSource.PLACEHOLDER
                        material.video_reference = reference
                    for material in tuple(lesson.materials):
                        if material.position not in active_positions:
                            await session.delete(material)
                if homework is None:
                    lesson.assignment = None
                elif lesson.assignment is None:
                    lesson.assignment = Assignment(
                        instructions=homework,
                        submission_kind=SubmissionKind.ANY,
                        is_required=True,
                    )
                else:
                    lesson.assignment.instructions = homework
                    lesson.assignment.submission_kind = SubmissionKind.ANY
                    lesson.assignment.is_required = True
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(update_practice_course())
