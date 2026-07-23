# Known limitations

## Phase 2 product limits

- FRED/ALFRED live calls require a user-supplied key. The delivery environment
  had no key, so the adapter was contract-tested with official response shapes
  and Demo data; live catalog validation remains an operator check.
- The adapter requests new and revised ALFRED observations in one large page.
  A provider response beyond FRED's 100,000-row limit needs explicit pagination
  before very deep full-history backfills are considered complete.
- State snapshots are computed deterministically on read. The
  `state_snapshots` table is retained for later scheduled materialization;
  `rebuild-state` currently validates/recomputes a snapshot rather than
  persisting a historical range.
- Fiscal and External have sparse component coverage and are explicitly marked
  experimental. All dimensions lower confidence when coverage or freshness is
  weak.
- Demo fixtures are deterministic and revision-aware but intentionally small.
  They demonstrate behavior; they are not economic facts and remain visibly
  labeled `DEMO`.
- Release-calendar ingestion is best effort because upstream scheduled-release
  coverage varies. Demo releases are visibly named and sourced as fixtures.
- The Windows launcher uses the Vite development server for a practical
  one-click local terminal. Packaging a static production server or Tauri
  installer is a later distribution step.
- The first launch requires internet access if locked Python/npm dependencies
  are not already cached. Node.js itself is detected but not silently installed.
- There is no automatic in-process scheduler yet. Startup launches a lightweight
  background sync; full backfills and history syncs are manual CLI operations.
- The FastAPI test client emits an upstream Starlette/httpx deprecation warning.
  Tests pass; dependency overrides are deferred.

## Verification environment limits

- Docker is not installed locally. PostgreSQL Alembic SQL compiles offline, while
  the existing Linux CI job owns the live PostgreSQL migration/container check.
- The Codex in-app browser connection failed in this Windows session, so visual
  browser automation was unavailable. HTTP readiness, API payloads, macro build,
  and actual launcher start/status/stop behavior were verified.
- The upstream project still has unrelated baseline failures in `test:data`,
  Buf lint, and some generated-artifact checks.
- The canonical upstream `build:full` wrapper contains POSIX file operations on
  Windows. Its outcome is recorded in the Phase 2 progress note; TypeScript/Vite
  macro and equivalent full build checks remain the relevant application gates.

Missing values are never replaced with zero. Live mode never intentionally
mixes Demo observations: the first successful live synchronization removes the
fixture rows for that series before inserting provider vintages.
