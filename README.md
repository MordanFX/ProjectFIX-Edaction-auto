# Mordan | Project FIX

Образовательная платформа из двух интерфейсов:

- Telegram-бот для прохождения курса учениками;
- веб-панель для кураторов и администраторов.

Обе части используют общую PostgreSQL-базу и общие SQLAlchemy-модели.
Полное продуктовое описание находится в `PROJECT_OVERVIEW.md`.

## Текущий этап

Готовы фундамент, основной учебный поток Telegram-бота, проверка ДЗ куратором,
FastAPI-бэкенд и первый рабочий React-интерфейс. Продакшен-деплой пока намеренно
не настраивается.

## Локальная подготовка

Требуется Python 3.12 или новее (до 3.15) и PostgreSQL.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Если Windows launcher не видит уже установленный Python 3.12 (как в текущем
окружении), создать среду можно по его полному пути:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
```

Затем укажите реальные локальные настройки в `.env`. Этот файл игнорируется Git.
Токен Telegram никогда не записывается в исходный код.

Для Discord укажите `DISCORD_BOT_TOKEN` и `DISCORD_GUILD_ID`. Discord — отдельный
учебный поток и не требует Telegram: команда `/homework` регистрирует участника и
создаёт его приватную ветку. Куратор назначает ему курс типа Discord в веб-панели.

Применение миграций:

```powershell
alembic upgrade head
```

Локальный запуск Discord-бота в отдельном терминале:

```powershell
python -m course_platform.discord
```

Проверки:

```powershell
pytest --cov
ruff check .
```

## Локальная demo-панель

Для локальной SQLite-базы сначала примените миграции и создайте demo-данные:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./.local/course.db"
alembic upgrade head
python -m course_platform.dev.seed_demo
```

Запуск API:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./.local/course.db"
$env:JWT_SECRET = "local-demo-secret"
uvicorn course_platform.api.app:app --reload
```

Запуск React в другом терминале:

```powershell
Set-Location frontend
npm install
npm run dev
```

Панель откроется по адресу `http://127.0.0.1:5173`. Локальная demo-учётная
запись: `demo-curator` / `demo-admin`. Demo-seed заблокирован при
`APP_ENV=production`.

Конфигурация продакшен-развёртывания намеренно пока не добавлена.
