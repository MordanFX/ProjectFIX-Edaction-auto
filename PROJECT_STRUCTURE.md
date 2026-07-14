# PROJECT_STRUCTURE.md

Рабочая карта проекта для разработки. Перед изменениями сначала смотреть этот файл, затем `CURRENT_STATE.md` и `TODO_NEXT.md`.

## Назначение проекта

Платформа обучения Project FIX:

- Telegram-бот для Telegram-потока учеников.
- Discord-бот для Discord-потока учеников.
- Веб-панель для администратора/кураторов.
- Общая база данных как точка интеграции.

Telegram и Discord — разные продукты/потоки. Их ученики, курсы, домашние задания и интерфейсы не должны смешиваться.

## Основные директории

```text
src/course_platform/
  api/                 FastAPI backend веб-панели
  bot/                 Telegram bot
  discord/             Discord bot
  models/              SQLAlchemy модели
  services/            бизнес-логика
  db/                  engine/session/base
  config.py            настройки окружения

frontend/
  src/App.tsx          главный shell панели и переключение разделов
  src/api.ts           клиент API
  src/types.ts         frontend-типы
  src/components/      страницы и модалки панели
  src/styles.css       основной CSS

migrations/
  versions/            Alembic migrations

tests/
  api/                 тесты FastAPI
  bot/                 тесты Telegram bot
  discord/             тесты Discord bot
  services/            тесты бизнес-логики
```

## Backend: API

Папка: `src/course_platform/api`

```text
app.py
  create_app(), подключение роутеров.

dependencies.py
  зависимости FastAPI: DB session, current staff, сервисы.

security.py
  hash паролей, JWT encode/decode.

schemas.py
  Pydantic request/response модели.

routers/auth.py
  /api/auth/token
  /api/auth/me

routers/reviews.py
  очередь ДЗ, детали работы, принятие/доработка,
  вложения ученика и вложения куратора.

routers/students.py
  Telegram-ученики, детали ученика, доступы/курс.

routers/discord.py
  Discord overview, участники, доступы, вопросы,
  выдача Discord-уроков в приватные ветки.

routers/courses.py
  курсы, уроки, группы, база уроков, обложки, импорт уроков.

routers/dashboard.py
  summary для Telegram dashboard.

routers/health.py
  healthcheck.
```

## Backend: модели

Папка: `src/course_platform/models`

Важные сущности:

```text
staff_users
  админы и кураторы панели/Telegram-режима.

students
  ученики Telegram и Discord, разделены origin.

courses / lessons / assignments
  курсы, уроки, домашние задания.

enrollments
  доступ ученика к курсу/потоку.

lesson_progress
  прогресс ученика по урокам.

submissions
  сдачи домашних заданий.

submission_attachments
  вложения ученика.

feedback
  решение/комментарий куратора.

feedback_attachments
  вложения куратора в ответе.

discord_participants / discord_homework_spaces
  Discord-участники и их приватные homework-пространства.

discord_questions
  вопросы ученика к куратору из Discord.

discord_lesson_dispatches / discord_lesson_deliveries
  рассылки Discord-уроков в приватные ветки.
```

## Backend: сервисы

Папка: `src/course_platform/services`

API и боты должны работать через сервисы, а не дублировать бизнес-логику.

Ключевые сервисы:

```text
admin_dashboard.py
  данные для Telegram dashboard/учеников.

course_admin.py
  управление курсами, уроками, группами, материалами.

students.py
  регистрация учеников, доступы, детали ученика.

progression.py
  движение ученика по урокам.

submissions.py
  создание и обработка сдач ДЗ.

reviews.py
  проверка ДЗ, feedback, история попыток, вложения куратора.

notifications.py
  pending notifications для отправки ботом.

discord_dashboard.py
  данные Discord workspace.

discord_participants.py
  Discord-участники и профили.

discord_submissions.py
  Discord-сдачи, вопросы и ответы.

discord_lesson_deliveries.py
  выдача Discord-уроков в приватные ветки.

discord_access.py
  доступы/сроки Discord-участников.
```

## Telegram bot

Папка: `src/course_platform/bot`

```text
application.py
  запуск polling.

router.py
  обработка /start, кнопок ученика, режима куратора,
  сдачи ДЗ, вопросов, проверки и выдачи курса.

api.py
  прямой async-клиент Telegram Bot API через httpx.

ui.py
  клавиатуры и тексты кнопок.

notifications.py
  отправка feedback ученику.

reminders.py
  напоминания и эскалации.
```

Telegram-бот не вызывает веб-панель. Он читает/пишет базу через сервисы.

## Discord bot

Папка: `src/course_platform/discord`

```text
application.py
  Gateway, slash-команды, кнопки Discord,
  /homework, приватные ветки, вопросы, сдача ДЗ.

client.py / rest.py
  REST-вызовы Discord API.

delivery.py
  отправка уроков/feedback в приватные ветки.
```

Discord-бот не зависит от Telegram-бота. Интеграция — через базу.

## Frontend

Папка: `frontend/src`

```text
App.tsx
  общий layout, левое меню, загрузка dashboard data,
  переключение разделов.

api.ts
  все HTTP-вызовы к backend.

types.ts
  типы API.

components/ReviewsSection.tsx
  Telegram ДЗ.

components/DiscordSection.tsx
  Discord ДЗ, вопросы, рассылки.

components/DiscordDispatchSection.tsx
  выдача Discord ДЗ/уроков.

components/DiscordStudentsSection.tsx
  Discord-ученики.

components/DiscordAccessSection.tsx
  доступы Discord.

components/StudentsSection.tsx
  Telegram-ученики.

components/CoursesSection.tsx
  курсы Telegram/Discord.

components/CourseModal.tsx
  редактор Telegram-курса.

components/DiscordCourseModal.tsx
  редактор Discord-курса.

components/KnowledgeBaseSection.tsx
  база знаний/уроки.

components/ReviewModal.tsx
  проверка работы, история попыток, вложения ученика/куратора.
```

## Docker/server

Сервер:

```text
167.233.113.236
```

Текущий проект:

```text
/opt/projectfix-education
```

Старый чужой/отдельный бот, не трогать:

```text
/opt/projectfix-bot
/etc/projectfix-bot/config.yaml
systemd service: forex-bot
```

Docker compose сервисы текущего проекта:

```text
api
frontend
telegram-bot
discord-bot
postgres
migrate
```

Проверка:

```powershell
ssh -i "$env:USERPROFILE\.ssh\projectfix_deploy" -o BatchMode=yes root@167.233.113.236 "cd /opt/projectfix-education && docker compose ps"
ssh -i "$env:USERPROFILE\.ssh\projectfix_deploy" -o BatchMode=yes root@167.233.113.236 "curl -fsS http://127.0.0.1:8081/api/health"
```

## Git

Remote:

```text
https://github.com/MordanFX/ProjectFIX-Edaction-auto.git
```

Перед любыми изменениями:

```powershell
git status --short
```

Не трогать чужие незакоммиченные изменения.
