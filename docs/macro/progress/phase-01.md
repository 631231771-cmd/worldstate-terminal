# Phase 1 progress

Status: complete on 2026-07-23.

## Delivered

- Python 3.12 `uv` project with a frozen lock, strict Ruff/mypy/pytest gates,
  optional `openbb==4.7.2`, and reproducible wheel/sdist builds;
- FastAPI lifecycle, request correlation, safe domain errors, Prometheus metrics,
  redacting structured logs, and `/v1/health`;
- normalized provider protocol and immutable metadata, observation, release, and
  provider-health models;
- YAML catalog loader with schema, canonical-key, provider/native-key, and
  availability-policy validation;
- sixteen SQLAlchemy entities and a complete initial PostgreSQL Alembic
  migration, with no production `create_all`;
- automation-safe CLI with implemented Phase 1 commands and explicit unsupported
  results for future commands;
- initial entity, state, causal, and provider catalogs without fabricated
  observations;
- non-root Dockerfile, PostgreSQL/Macro Engine/World Monitor Compose stack,
  environment example, Make targets, and a dedicated CI workflow;
- API, operations, security, third-party, limitation, risk, and customization
  records.

## Acceptance matrix

| Required delivery | Evidence |
| --- | --- |
| FastAPI | app factory, lifespan, health, metrics, OpenAPI |
| PostgreSQL | async SQLAlchemy models and PostgreSQL-specific migration |
| Alembic | `0001_initial_schema`; offline SQL generation passes |
| Provider protocol | runtime-checkable asynchronous `MacroProvider` |
| catalog loader | four catalog files, eight series, structural validation |
| health API | explicit DB/provider states; secret-free failure test |
| Docker Compose | three-service topology and health dependencies |
| CLI | help plus implemented/unsupported command tests |
| CI | Python 3.12, locked sync, lint, types, tests, live migration, image build |
| test skeleton | 25 tests; 96.76% branch coverage |

## Verification

### Macro Engine

- `python -m uv lock --check`: pass, 140 locked packages;
- default development sync: pass, 56 installed packages, OpenBB not installed;
- `ruff format --check .`: pass, 35 files;
- `ruff check .`: pass;
- `mypy src tests`: pass, 33 files;
- `pytest`: 25 passed, 96.76% branch coverage;
- catalog validation: four files, eight series, no errors;
- Alembic offline PostgreSQL SQL generation: pass;
- Python wheel and source distribution build: pass.

### Upstream regression

- documentation claim check: pass, 80 claims;
- frontend and API TypeScript checks: pass;
- lint: pass with the pinned upstream baseline of 25 warnings and 3 infos;
- safe HTML guard: pass;
- sidecar/API tests: 250 passed;
- full variant TypeScript/Vite/PWA production build: pass, 2,359 modules.

## Environment-limited checks

The local machine has no Docker CLI, so a live Compose boot, PostgreSQL migration,
and container image build could not run locally. Static Compose/Dockerfile
invariants pass. The dedicated Linux CI job runs a PostgreSQL 16 service, applies
the migration, validates the catalog, and builds the container.

The existing upstream `test:data`, Buf, canonical `build:full` wrapper, and local
browser-E2E limitations remain documented in `BASELINE.md` and
`KNOWN_LIMITATIONS.md`; none is caused by Macro Engine.

## Phase boundary

Phase 1 does not ingest live observations, compute state, modify a frontend
variant, add gateway/proto contracts, or bundle Python into Tauri. Those
capabilities begin in Phases 2 and 3.
