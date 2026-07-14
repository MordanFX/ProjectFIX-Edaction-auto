# Project FIX Education

Образовательная платформа Project FIX:

- Telegram-бот для Telegram-потока учеников.
- Discord-бот для Discord-потока учеников.
- Веб-панель для администратора и кураторов.
- Общая PostgreSQL-база как точка интеграции.

## Основные рабочие документы

Перед изменениями смотреть:

1. `AGENTS.md` — правила работы AI-агента и ограничения проекта.
2. `PROJECT_STRUCTURE.md` — карта директорий, модулей, сервисов и ответственности.
3. `CURRENT_STATE.md` — что уже реализовано и как сейчас работает продукт.
4. `TODO_NEXT.md` — ближайший план разработки.

## Архитектурный принцип

Telegram, Discord и веб-панель не вызывают друг друга напрямую.

```text
Telegram bot ┐
Discord bot  ├── PostgreSQL ── Web panel
FastAPI API  ┘
```

Telegram-ученики и Discord-ученики — разные потоки. Их нельзя смешивать в UI и бизнес-логике.

## Локальные проверки

Backend:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest --cov
```

Frontend:

```powershell
cd frontend
npm run build
```

## Сервер

Текущий проект:

```text
/opt/projectfix-education
```

Не трогать старый отдельный проект:

```text
/opt/projectfix-bot
/etc/projectfix-bot/config.yaml
systemd service: forex-bot
```
