FROM ghcr.io/astral-sh/uv:0.11.31-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY services/macro-engine/pyproject.toml services/macro-engine/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/macro-engine/README.md ./README.md
COPY services/macro-engine/alembic.ini ./alembic.ini
COPY services/macro-engine/migrations ./migrations
COPY services/macro-engine/src ./src
COPY data/macro ./data/macro
RUN uv sync --frozen --no-dev

RUN groupadd --system macro && useradd --system --gid macro --home-dir /app macro \
    && chown -R macro:macro /app
USER macro

ENV MACRO_CATALOG_ROOT=/app/data/macro
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=3)"]

CMD ["uv", "run", "--no-sync", "macro-engine", "serve", "--host", "0.0.0.0", "--port", "8000"]

