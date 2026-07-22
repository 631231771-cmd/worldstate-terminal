# World State Terminal implementation plan

## Delivery rules

Each phase ends with focused tests, static analysis, a production build where the
phase has a build artifact, an updated progress record, and a single-scope commit.
Existing variants and upstream attribution remain intact.

## Phase 0: upstream audit and plan

- pin upstream and establish the feature branch;
- audit architecture, contribution rules, runtime versions, tests, builds, proto,
  E2E, and license posture;
- record baseline failures without broad upstream remediation;
- establish architecture boundaries, risks, decisions, and customization tracking.

## Phase 1: Macro Engine skeleton

- create the Python 3.12 `uv` project and strict mypy/Ruff/pytest configuration;
- define settings, redacted structured logging, FastAPI lifecycle, and health API;
- define SQLAlchemy entities and a complete initial Alembic migration;
- define provider protocol and normalized metadata/observation/release/health types;
- load and statically validate YAML catalogs without requiring live credentials;
- implement CLI help and Phase 1 commands with explicit unsupported summaries;
- add PostgreSQL/Macro Engine/web Docker Compose and example environment;
- add CI for lint, types, unit tests, migration checks, and container build.

## Phase 2: FRED/ALFRED and deterministic state

- implement official vintage/realtime ingestion, idempotent sync, and release data;
- add at least 35 catalog series and validate metadata;
- implement point-in-time filters, transforms, weighted median, confidence, state
  history, drivers, changes, and release calendar;
- prove strict look-ahead safety and revision reproducibility with property tests.

## Phase 3: macro variant and gateway

- define MacroService proto and generated clients/handlers;
- add the seventh variant and six-panel default layout;
- add bilingual state, map, change, regime, rates, and calendar panels;
- preserve full, finance, commodity, tech, happy, and energy builds.

## Phase 4: Series Lab and countries

- add revision-aware, as-of-aware chart APIs and UI;
- integrate World Bank and BIS with coverage diagnostics;
- implement country snapshots, comparison, and choropleth rendering.

## Phase 5: Causal Atlas and Thesis Book

- load human-authored causal YAML with conditions, lags, evidence, and exceptions;
- implement thesis CRUD, conditions, evidence, evaluation, and immutable snapshots.

## Phase 6: Daily Brief and optional AI/MCP

- produce an evidence-linked deterministic brief;
- expose structured macro tools;
- add optional Ollama/OpenRouter explanation with evidence enforcement.

## Phase 7: stabilization

- complete data health, last-known-good behavior, performance budgets, security
  review, backup/restore, E2E, documentation, and upstream-diff review.

## Phase 1 expected file surface

- `services/macro-engine/**`
- `data/macro/**`
- `docker-compose.macro.yml`
- `.env.macro.example`
- `.github/workflows/macro-engine.yml`
- `docs/macro/**`

Phase 1 does not modify frontend variant, panel, gateway, proto, or Tauri runtime
files. Those boundaries are intentionally deferred to Phase 3.
