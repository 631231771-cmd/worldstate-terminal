# Macro Engine operations

Status: Phase 1 skeleton.

## Prerequisites

- Python 3.12 managed by `uv`;
- PostgreSQL 16 for production and integration checks;
- Docker Compose for the unified local stack.

The default Python environment does not install OpenBB. Add the `openbb` extra
only when a provider implementation requires it.

## Local setup

From `services/macro-engine`:

```powershell
python -m uv sync --locked --group dev
python -m uv run macro-engine catalog validate
python -m uv run macro-engine serve
```

The service starts without a FRED key. Health then reports the provider as
`not_configured`.

## Database

Set `MACRO_DATABASE_URL` to a PostgreSQL async URL, then run:

```powershell
python -m uv run macro-engine migrate
```

Production schema changes use Alembic only. Application startup must not call
SQLAlchemy `create_all`.

## Unified stack

From the repository root:

```text
docker compose -f docker-compose.macro.yml up --build
```

The stack starts PostgreSQL, applies migrations, validates the catalog, then
starts Macro Engine and World Monitor. PostgreSQL data lives in the named
`macro-postgres-data` volume. Macro Engine is exposed on loopback by default.

## Configuration

Copy `.env.macro.example` to a local untracked environment file. Keep provider
keys, database passwords, AI keys, and write tokens out of Git and browser
bundles.

Important controls:

- `MACRO_STRICT_POINT_IN_TIME=true`;
- `MACRO_ENABLE_WRITES=false`;
- `MACRO_WRITE_TOKEN` unset until writes are explicitly required;
- `MACRO_DEFAULT_LOCALE=zh-CN`;
- `MACRO_DEFAULT_TIMEZONE=Asia/Taipei`.

## Verification

```powershell
python -m uv run ruff format --check .
python -m uv run ruff check .
python -m uv run mypy src tests
python -m uv run pytest
python -m uv lock --check
```

## Backup, restore, and upgrade

Phase 1 contains only schema and no production observations. PostgreSQL-native
backup/restore runbooks, compatibility windows, and data migration rehearsals
are Phase 7 deliverables. Until then, do not treat a container volume as a
backup.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| health is degraded | database reachability and `MACRO_DATABASE_URL` |
| provider is `not_configured` | expected without the provider credential |
| catalog is invalid | run `macro-engine catalog validate` and inspect errors |
| command exits 3 | command is a declared future-phase surface |
| container cannot become healthy | migrations, catalog mount, then `/v1/health` |
