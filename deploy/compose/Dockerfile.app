FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir uv==0.10.4

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY services ./services
COPY src ./src
COPY apps ./apps
COPY docs/contracts/demo-analysis-cases-v0.2.json ./docs/contracts/demo-analysis-cases-v0.2.json
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY deploy/modal/app.py ./deploy/modal/app.py
COPY deploy/modal/requirements.txt ./deploy/modal/requirements.txt

# Modal is pinned separately until it is added to uv.lock.
RUN uv sync --locked --group dev \
    && uv pip install --python /app/.venv/bin/python -r deploy/modal/requirements.txt

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
