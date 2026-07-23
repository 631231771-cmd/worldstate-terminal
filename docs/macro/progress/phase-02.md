# Phase 2 progress

Status: complete on 2026-07-23.

## Delivered

- root `WorldState.bat` with `start`, `stop`, `restart`, `status`, `sync`,
  `doctor`, and `logs`;
- repository-local `.runtime` config, SQLite database, PID files, and logs;
- locked dependency setup, Alembic migration, readiness waits, safe process-tree
  ownership checks, background initialization, and browser launch;
- SQLite desktop default with the same models/migration retained for PostgreSQL;
- explicit `LIVE`, `STALE`, `DEMO`, and `EMPTY` behavior;
- practical FRED/ALFRED metadata, observation, vintage, revision, release, and
  provider-health adapter;
- 38-series U.S. catalog with per-series transform, orientation, weight,
  freshness, minimum history, and state mapping;
- idempotent synchronization, preserved vintages, recent sync, backfill,
  revision-history sync, rebuild, and data-health commands;
- deterministic Demo observations with explicit revisions and release fixtures;
- point-in-time series queries and missing-safe transforms;
- eight explainable state scores, confidence, trend, drivers, missing/stale
  metadata, experimental flags, regime trajectory, and Top Changes;
- `/v1/snapshot`, `/v1/series`, and `/v1/series/{key}` APIs;
- `dev:macro` and `build:macro` frontend variant with default Simplified Chinese,
  English toggle, Asia/Taipei dates, centralized API client, and explicit data
  mode;
- World State, Top Changes/release calendar, Growth–Inflation Regime, Series
  Explorer, and System Status panels.

## Verification

- real SQLite upgrade from empty database: pass;
- root launcher start/status/stop: pass; both owned ports released after stop;
- Demo sync: 10,132 inserted observations, 38 series, eight states;
- second Demo sync: idempotent, zero inserts/updates;
- PostgreSQL Alembic offline SQL compile: pass;
- `ruff check src tests`: pass;
- strict `mypy src`: pass;
- Macro Engine tests: 27 passed, 88.50% coverage;
- root TypeScript typecheck: pass;
- `build:macro`: pass, 2,364 modules and PWA output;
- canonical `build:full`: reached and passed the blog build, then hit the known
  Windows-only `rm` wrapper failure;
- equivalent full `tsc && vite build`: pass, 2,364 modules and PWA output;
- environment-secret, safe-HTML, and local-environment security checks: pass;
- no runtime database, environment file, PID, log, or generated index changes
  are tracked; `git diff --check`: pass.

## Environment notes

No FRED key or Docker CLI was available. Live HTTP behavior is covered with
provider-contract fixtures; a user key is required for operational validation.
The in-app browser connection failed, so UI automation was replaced by real
service readiness, HTTP payload, production build, and launcher lifecycle
checks.

## Commit

Implementation commit:
`d144c96a6afcf674e854e80feefbfa66cdbf8549`
(`feat(macro): deliver local-first World State Terminal MVP`).
