FROM ghcr.io/astral-sh/uv:0.11.31-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    WORLDSTATE_DATABASE_URL=sqlite+aiosqlite:////data/worldstate.db

WORKDIR /app

COPY services/research-api/pyproject.toml services/research-api/uv.lock \
    services/research-api/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/research-api/alembic.ini ./alembic.ini
COPY services/research-api/migrations ./migrations
COPY services/research-api/src ./src
COPY data/macro ./data/macro
COPY data/fixtures ./data/fixtures
RUN uv sync --frozen --no-dev

RUN groupadd --system worldstate \
    && useradd --system --gid worldstate --home-dir /app worldstate \
    && mkdir -p /data \
    && chown -R worldstate:worldstate /app /data
USER worldstate

ENV WORLDSTATE_ROOT=/app \
    WORLDSTATE_CATALOG_ROOT=/app/data/macro \
    WORLDSTATE_FIXTURE_PATH=/app/data/fixtures/macro-research-demos.json
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v2/health', timeout=3)"]

CMD ["/app/.venv/bin/python", "-m", "worldstate.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
