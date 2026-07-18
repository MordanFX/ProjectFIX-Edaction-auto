FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src
# Lesson materials may reference bundled course images by repo-relative path.
COPY frontend/public/course-assets ./frontend/public/course-assets

RUN python -m pip install --upgrade pip \
    && python -m pip install .

CMD ["uvicorn", "course_platform.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
