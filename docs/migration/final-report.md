# Migration final report

## Outcome

The active product is now a macro research terminal. The former news, map,
geopolitical, aviation, maritime, surveillance, commerce and multi-variant
surfaces were deleted from the active tree after preservation at tag
`world-monitor-legacy-freeze` and branch `archive/world-monitor-legacy`.

The product and active code-tree migration is complete. Research-method and
release truthfulness stabilization is still being validated; PR #8 remains
Draft and unmerged by explicit instruction. This statement does not mean
real-data coverage or self-contained installer packaging is complete.

## Retained and replaced

Retained concepts: local desktop delivery, provider isolation, caching-oriented
ingestion, API delivery and AI integration. They were reimplemented behind
macro-specific boundaries.

Replaced:

- generic/news `Event` → `MacroRelease`, `ReleaseStage`, append-only values;
- finance/news cards → cross-asset event windows and market reactions;
- unrestricted summary flow → structured EvidencePack and validation;
- World Monitor SPA/Vercel endpoints → Preact terminal and FastAPI `/v2`;
- old Tauri/Node sidecar → small Tauri shell for the Research API.

## Database

Alembic revision `0003_macro_research_terminal` creates the v3 model, backfills
valuable CPI-v2 rows, validates references and removes semantic duplicates.
Revision `0004_analysis_reproducibility` adds immutable AnalysisRun manifests,
Regime dimensions, matched-run references, EvidenceItems and ResearchClaims.
Clean-environment migration and upgraded-copy migration are both covered. Use
`research/validation/verify_migration.py` for a read-only post-check.

## API and UI

`/v2` exposes calendar, releases, stages, values, consensus, windows, reactions,
timeline, historical matches, explanations, reports, EvidencePack, providers,
quality, regimes, methods and local write/import/analyze operations. v0.4 adds
run manifest, replay, diff, claims and evidence endpoints plus idempotent
analysis creation.

The UI has exactly five top-level workspaces: Today, Macro Releases, Event Lab,
Cross Asset, and Data & Methods. CPI, NFP and FOMC are navigable end to end.
Event Lab distinguishes threshold scaling from Z-score, shows immutable run
hashes, renders structured claim/evidence bindings and labels the experimental
calendar precision.

The verified FOMC Event Lab render is preserved at
[`docs/architecture/assets/event-lab-fomc.png`](../architecture/assets/event-lab-fomc.png).

## Data sources and limits

Official-source and point-in-time interfaces exist, with FRED/ALFRED as the
first optional adapter. Consensus and minute bars currently rely on
manual/CSV/fixture paths unless an optional provider is configured. Fixture,
proxy, delay, granularity and contamination are visible.

The current evidence supports explanation of consistency with transmission
chains, not identification of unique causal order flow. Historical statistics
remain limited until a larger licensed point-in-time sample is imported.

## Verification

Verified locally on Windows on 2026-08-02 (final GitHub results are recorded in
the v0.4 stabilization report):

- Ruff: passed.
- strict mypy: passed for 64 Python source/test files.
- pytest: 63 tests passed, 68.88% branch-aware repository coverage and 96%
  aggregate critical research-method coverage (90% gate).
- terminal UI TypeScript and production Vite build: passed.
- database v3 + v0.4: both an upgraded working database and a clean database passed
  required-table and orphan-reference validation.
- Tauri: unit tests, `cargo fmt --check`, `cargo check`, and a debug `tauri build
  --no-bundle` passed; the generated executable remained alive in a launch
  smoke test.
- browser: all five workspaces rendered, the FOMC four-stage view and `-0.30`
  composite score appeared, and no console/page errors were observed.

Known validation limits: Docker is not installed on the verification machine,
PostgreSQL was not exercised, and the Starlette TestClient emits one upstream
httpx deprecation warning. A signed, self-contained Python-sidecar installer is
still packaging work; the BAT launcher is the verified daily-use path.

Launcher use is consolidated to exactly three layers: desktop
`WorldState Terminal.bat`, repository `WorldStateApp.bat`, and maintenance
`WorldState.bat <command>`. Confirmed obsolete desktop entries were preserved in
the dated desktop archive and are not active launch methods.
