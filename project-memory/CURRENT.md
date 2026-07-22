---
project: World State Terminal
status: phase-1-wip
updated: 2026-07-22
branch: feature/world-state-terminal
phase_1_checkpoint: 7d70d3d2ee8d4476a5c310a62274b6952ccc7865
resume_from: dependency-lock-and-verification
---

# Current continuation point

> [!important] Resume here
> Phase 0 is complete. Phase 1 implementation is saved as an intentionally
> unverified WIP commit. Do not treat Phase 1 as complete until its lockfile,
> strict checks, tests, build, progress report, and final phase commit pass.

## Repository state

- Repository: `F:\Code\world\worldstate-terminal`
- Branch: `feature/world-state-terminal`
- Upstream baseline: `7fe22e47dc90ee2693d0071323561e5bbffe5c42`
- Phase 0 commit: `8059b7aaa0fe8c2ef24774a5998c0695d391abeb`
- Phase 1 WIP checkpoint: `7d70d3d2ee8d4476a5c310a62274b6952ccc7865`
- Worktree was clean immediately after the WIP commit.
- Git remote is named `upstream` and points to `koala73/worldmonitor`.

## Completed

- Cloned and pinned the upstream World Monitor baseline.
- Created `feature/world-state-terminal`.
- Ran and recorded the upstream baseline checks.
- Completed and committed Phase 0 documentation under `docs/macro/`.
- Installed `uv 0.11.31` and uv-managed Python 3.12.13 locally.
- Added the Phase 1 Macro Engine skeleton under `services/macro-engine/`.
- Added typed configuration, structured redacting logs, provider protocol,
  catalog validation, health API, metrics endpoint, and CLI command surface.
- Added SQLAlchemy models and Alembic migration for all 16 planned entities.
- Added initial macro catalogs without fabricated observations.
- Added Dockerfile, Compose stack, CI workflow, environment example, Make
  targets, and initial unit tests.

## Exact next actions

1. In `services/macro-engine`, run `python -m uv lock`.
2. Run `python -m uv sync --group dev`.
3. Run Ruff, fix all findings, then run strict mypy and fix all findings.
4. Run pytest with the configured coverage threshold and close coverage gaps.
5. Validate the CLI help, catalog command, and Alembic offline SQL generation.
6. Validate Docker Compose configuration and build the Macro Engine image if
   Docker is available.
7. Re-run relevant root checks: documentation checks, TypeScript typecheck,
   lint, and a production frontend build.
8. Add `docs/macro/progress/phase-01.md`, update limitations/customizations,
   run secret and diff checks, then make the formal Phase 1 commit.

## Likely first fixes

- Correct FastAPI middleware typing in `macro_engine/main.py`.
- Use `pytest.MonkeyPatch` types in configuration and health tests.
- Ensure the Dockerfile copies `README.md` before the frozen dependency sync.
- Resolve any Ruff or mypy findings in the large ORM and migration modules.
- Confirm the optional `openbb==4.7.2` extra does not affect the core sync.

## Known baseline constraints

- Root `typecheck`, `typecheck:all`, lint, sidecar tests, and finance build pass.
- `test:data` already fails upstream for generated-artifact drift, Windows path
  assumptions, missing `dist`, locale size, and other unrelated contracts.
- `build:full` uses POSIX `rm` and fails on Windows; the equivalent direct full
  Vite build passes.
- Standard Playwright startup uses POSIX environment syntax on Windows, and the
  Chromium download timed out, so browser smoke testing is still unavailable.
- Buf lint has pre-existing protobuf naming/import/package findings.
- Never use fabricated macro data. Missing providers must remain explicit.

## Guardrails

- Preserve upstream behavior and isolate new macro functionality.
- Never log or commit provider keys, tokens, database credentials, or AI keys.
- Writes require both `MACRO_ENABLE_WRITES=true` and a configured write token.
- Use SQLite only for isolated tests; PostgreSQL and Alembic are authoritative.
- Run heavy verification commands serially on this machine.
- Do not amend the WIP checkpoint merely to hide intermediate history; finish
  Phase 1 with a separate verified phase commit.

## Canonical links

- [[00-checkpoints/2026-07-22-phase-1-wip]]
- [Phase 0 progress](../docs/macro/progress/phase-00.md)
- [Implementation plan](../docs/macro/plan/IMPLEMENTATION_PLAN.md)
- [Known limitations](../docs/macro/KNOWN_LIMITATIONS.md)
- [Customization ledger](../docs/macro/CUSTOMIZATIONS.md)
- [Upstream record](../docs/macro/UPSTREAM.md)
