FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONPATH=/app:/app/src \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir uv==0.10.4 \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app

# Install third-party dependencies before copying application code so source
# edits do not invalidate the expensive dependency layer. The project itself
# is imported from /app and /app/src through PYTHONPATH.
COPY pyproject.toml uv.lock ./
COPY deploy/modal/requirements.txt ./deploy/modal/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --group dev --no-install-project \
    && uv pip install --python /app/.venv/bin/python -r deploy/modal/requirements.txt

COPY services ./services
COPY src ./src
COPY apps ./apps
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY deploy/modal/app.py ./deploy/modal/app.py

USER appuser
