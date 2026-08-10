# CURRENT — WorldState Macro Research Terminal

Updated: 2026-08-10

## Product truth

WorldState is a personal macro research and trading-assistance terminal. Its
daily job is to answer: what was released, how it differed from consensus, how
cross-assets reacted, what historical analogues show, and how confident an
evidence-bounded explanation should be.

World Monitor's news wall, world map and geopolitical-monitoring modules are no
longer part of the active architecture. Their final state is preserved at tag
`world-monitor-legacy-freeze` and branch `archive/world-monitor-legacy`.

## Active branch and milestones

- Working branch: `feature/v0.7-live-global`
- Last committed v0.4 baseline: `16544c373bb32fc9788b72538db49c3fcc2c1337`
- v0.5 Data Foundation: committed as `4054a66e620db2f5aff9a4c70b6af9be3b9aad94`; local and GitHub CI validation complete
- Database head in the worktree: `0010_operational_state_defaults`
- API contract: `/v2`
- Product version in the worktree: `0.7.0`
- HEAD: `bd177d1` (`feat: productize v07 terminal workflow`; keep PR #10 Draft)
- Runtime checkpoint: database migrated to `0010_operational_state_defaults`; one observed world-state snapshot, 8,801 observed daily context bars, 50 catalog series with 29,701 observed macro observations, 28,247 FRED current-public observations and 621 BLS current-state observations are present. FRED no-key data is explicitly current-state/non-PIT; a FRED key is still required for ALFRED vintage semantics.
- Runtime audit: `docs/macro/v0.7-live-coverage-audit-2026-08-10.md` records USA/EA/UK observed state coverage, Japan/China unavailable without an official export, 8 context instruments, one observed snapshot, zero observed consensus snapshots, and explicit market/data-quality boundaries.
- PR #8: Draft, unmerged; PR #9: Draft, open; PR #10: Draft, open on
  `feature/v0.7-live-global`; do not mark any of them Ready or merge

## Daily use

Use only these launcher layers:

- Desktop: `C:\Users\Administrator\Desktop\WorldState Terminal.bat`
- Repository: `WorldStateApp.bat`
- Maintenance: `WorldState.bat <command>`

```powershell
.\WorldState.bat start
.\WorldState.bat status
.\WorldState.bat stop
.\WorldState.bat data-doctor
.\WorldState.bat data-status
```

Terminal: `http://127.0.0.1:4173/#today`

The duplicate Chinese BAT and obsolete PySide shortcut were hash-verified and
archived on 2026-07-31. Do not restore them or modify the desktop archive.

## Stable v0.4 research capabilities

- CPI bundle: headline/core, MoM/YoY, revisions and composite classification.
- NFP bundle: payrolls, unemployment and wages with cross-unit revision safeguards.
- FOMC statement, press conference, key-Q&A and end stages with stage reversal.
- Cross-asset windows, earliest significant observed reaction and reversal.
- Fixed historical matching with sample thresholds, regime and contamination dimensions.
- Data quality, proxy and fixture disclosures.
- Reproducible AnalysisRun manifests/replay and structured Claim → Evidence binding.
- Experimental `exchange-session-lite` calendar with explicit limitations.
- Tauri product health verification, foreign-port refusal and AI secret forwarding.

The bundled CPI/NFP/FOMC slices are traceable fixture demonstrations. They are
not live or licensed historical datasets.

## v0.5 Data Foundation implemented; v0.5.1 truthfulness stabilization in progress

- Typed BLS, Federal Reserve, FRED/ALFRED, Trading Economics and Databento adapters.
- `observed` / `fixture` isolation across core records and analysis queries.
- Provider entitlement, quota, run, raw artifact and idempotency persistence.
- Durable sync job/run, calendar snapshot, market-data manifest, reconciliation
  and bounded backfill-job models in migration `0005_provider_data_foundation`.
- Follow-up migrations `0006_data_mode_integrity` and `0007_truthfulness_stabilization` upgrade databases that already
  applied the earlier local 0005 shape; it isolates Observation/ProviderRun/
  CalendarSnapshot identities by data mode without deleting existing rows.
- Non-blocking local scheduler and recoverable backfill worker are attached to
  the Research API lifecycle. First startup catches up today's missed daily
  work once; every cycle recovers stale runs without blocking desktop startup.
- v0.5.1 truthfulness policy: Today only returns released, completed and
  reproducibility-complete research for the requested data mode; Regime never
  falls back from observed to fixture. Missing credentials/entitlements and
  paid-download-disabled outcomes are blocked/partial, not failed.
- Durable official/consensus/market orchestration: BLS releases, FRED/ALFRED
  observations, Federal Reserve 2015–2020 archives plus current/future meetings,
  TE snapshots and Databento event-linked manifests.
- Databento execution requires a fresh provider quote, explicit paid opt-in,
  credential/entitlement and both per-slice and cumulative USD budget approval.
  A fallback estimate can inform setup but can never authorize paid download.
- `/v2/data/providers`, `/v2/data/coverage`, backfill estimate/job/status/cancel
  API boundaries and corresponding existing-terminal UI panels.
- CLI/launcher diagnostics for provider status, coverage and backfill estimates.

## v0.6 Operational Macro Intelligence implemented in checkpoints

- `wst-state-v1` deterministic World State engine reads the existing
  Series/Observation point-in-time layer and returns Growth, Inflation,
  Liquidity, Policy Tightness, Credit, Risk, Fiscal and External dimensions
  with score, direction, momentum, coverage, freshness, drivers, evidence IDs
  and data gaps.  `/v2/world-state` never falls back between data modes.
- `wst-daily-brief-v1` powers `/v2/daily-brief` and the upgraded Today page:
  World State, Top Changes, recent releases, market confirmation, revisions,
  upcoming events and Watch Next are generated deterministically.  AI is not
  required for the daily entry point.
- `/v2/market-dashboard` and the Markets workspace show 1D/1W/1M/3M changes,
  empirical percentiles, provider/granularity, proxy labels and gaps.
- `/v2/series` and `/v2/series/{canonical_key}` provide Series Explorer
  search, raw/MoM/YoY/3M annualized/percentile/z-score/moving-average views;
  transforms never mutate raw vintages.
- Migration `0008_thesis_book` adds the user-owned Thesis Book.  Thesis
  creation/update/evaluation and `/v2/research/assistant/context` expose
  structured context without auto-confirming a user hypothesis.
- `/v2/global-macro` and the Countries workspace provide a shallow first layer
  for US, China, Euro Area, Japan and UK.  Uncovered countries are shown as
  unavailable; the Context Layer cards are a framework, not live coverage.
- Demo mode has a separate `worldstate_state_fixture` provider and fixture
  observations for state cards.  They are excluded from observed queries.

The v0.6 implementation is a usable local research surface, not a claim of
complete live global coverage.  Official FRED/BLS/Fed observations, licensed
consensus and minute market data remain governed by the v0.5 provider and
entitlement boundaries below.

## v0.7 Live Data Activation & Global Macro

- Public no-key adapters now cover the ECB Data Portal and Bank of England
  IADB, with explicit adapter boundaries for BOJ and China official exports.
- FRED catalog sync is no longer limited to the five v0.5 foundation series;
  configured FRED credentials can populate the full catalog without mixing
  fixture rows into observed queries.
- `/v2/data/sync/public`, `/v2/data/bootstrap-free`, `/v2/data/freshness`,
  `/v2/macro-systems`, world-state history and watchlist endpoints are live.
- The Data Control Center shows provider entitlement, observed-series
  freshness, missing data and a bounded public bootstrap action.
- Freshness uses both retrieval age and covered-period age. A recent fetch does
  not make an old monthly or quarterly observation appear live.
- FRED public graph CSV is available without a key for current-state
  observations. It is marked `source_mode=current_public_csv`,
  `point_in_time=false`, quality B and `ingestion_time_proxy`; it must not be
  used for historical first-print or PIT backtests. With a FRED key, the
  existing ALFRED path remains the only vintage-aware route.
- FRED S&P 500, VIX, WTI, Brent, broad dollar, 2Y and 10Y series are persisted
  as daily `context_only`/`not_event_window` bars. They support daily context
  changes, not minute event windows, futures settlement or cash-yield claims.
- Data Control exposes a traceable `official macro CSV` import for Japan,
  China and other official exports. It always writes observed rows with a
  source artifact, manual/verification flags and a quality record; missing
  vintage/availability columns are explicitly non-PIT.
- Migration `0009_operational_state` stores immutable daily state snapshots and
  user watchlist entries. A real runtime copy was backed up before migration.
- Global macro comparison and system cards use only observed Series/Observation
  rows and report coverage, gaps, limitations and divergence without causal
  claims.
- Runtime validation on 2026-08-10 reached official BLS, FRED public graph,
  ECB and Bank of England endpoints. The runtime contains 50 series, 29,701
  observed macro rows, 8,801 observed market-context rows and 8 context
  instruments. Macro systems report 4/4, 4/4, 5/5 and 3/3 observed
  components; Japan and China remain unavailable until an official export is
  imported. Freshness is LIVE 35 / STALE 15 / MISSING 0 for this runtime.
- v0.7 final checks: 181 backend tests passed, Ruff and strict mypy passed,
  Terminal UI production build passed, Tauri fmt/check and 4 unit tests passed,
  and the data-control page was read in the running browser against the v0.7
  API. HICP correctly displayed `STALE` based on covered period age.

Detailed v0.7 evidence and limits are in
[`docs/macro/v0.7-live-global.md`](../docs/macro/v0.7-live-global.md).

## v0.7 Productization & Architecture Rationalization

- The terminal's primary navigation is grouped into Overview, Markets, Macro,
  Events, Research and Advanced. Data Sources and Data & Methods remain
  available as advanced surfaces.
- Today is the default daily entry; event selection is limited to event pages.
  Learning Mode is an opt-in contextual explanation layer.
- Data Sources now uses modal forms instead of `window.prompt` for FRED keys,
  market context imports and official macro CSV imports.
- Shared `DetailsDisclosure`/`Modal` primitives and a workspace error boundary
  provide progressive disclosure and page-level failure isolation.
- Market dashboard and Daily Brief market confirmation resolve quality from
  persisted `DataQualityRecord`; provider names no longer imply quality A/B.
- The frontend no longer falls back from `/v2/data/providers` to the legacy
  `/v2/providers` status projection.

Details: [`docs/macro/v0.7-productization.md`](../docs/macro/v0.7-productization.md).

## Honest incomplete boundaries

- Sync commands and reconciliation are wired and return honest
  `completed`/`partial`/`blocked` results. The backfill worker consumes approved
  jobs, retains partial results and cannot bypass paid-data gates.
- The validation environment has no FRED, Trading Economics or Databento key.
  FRED current public CSV is usable without a key, but ALFRED/PIT remains a
  credential blocker; TE historical replay additionally requires
  PIT entitlement, and Databento additionally requires dataset rights, explicit
  paid opt-in and budget approval. BLS does not require a key in public mode.
- BLS schedule HTML returned HTTP 403 from the current validation network. This
  is an environment/source-access blocker surfaced as a typed error; it is not
  silently replaced with fixture data. Federal Reserve public pages were
  independently reachable and verifiable.
- BLS current API is not a historical vintage archive. It cannot reconstruct
  old first prints from today's revised series.
- FOMC historical meetings are sourced from official 2015–2020 archive pages;
  current/future meetings keep scheduled statement/press stages. Unverified
  `key_qa` and `press_end` timestamps remain absent rather than being invented.
- Trading Economics and Databento depend on account entitlements, quotas and
  licence terms. Raw proprietary/market payloads stay local and are not
  redistributed.
- On-time TE T-24h/T-1h/T-5m/T+5m jobs use a current capture. Only missed
  historical replay requests PIT. TE health is configuration-only and consumes
  zero calendar quota; a successful sync is the live-health evidence.
- Analysis uses only bars attributable to release-linked manifests. Short
  windows use minute bars; long T+1/T+5/session returns require daily or declared
  session-close data. Databento UTC-day `ohlcv-1d` is an experimental grade-C
  proxy, not an exchange settlement/close; unavailable semantics produce a gap.
- DX/VX are futures. ZT/ZN are Treasury-futures price proxies, not exact cash
  yield basis-point series.
- Python is not frozen into a sidecar; the current desktop build is not a
  standalone signed installer for a blank computer.
- In a no-key observed database, World State, Daily Brief market confirmation,
  Series Explorer and global country cards can still be partial. The UI
  displays those gaps rather than substituting demo rows; current FRED context
  is not a replacement for licensed minute/event data.
- The first global layer has reliable observed coverage only where a provider
  has populated the Series/Observation catalog; the other country cards are
  scaffolding with explicit `unavailable` status.

- On 2026-08-10 the public BLS current-state sync completed (659 rows read,
  532 written in the five-year catch-up; 621 observed rows remain after
  deduplication), adding nine observed USA CPI/employment/wage/participation
  series. These are current captures with `point_in_time=false`; they are not
  historical first-print release data. The public API emitted two
  calculation-disabled warnings; percentage rows derived from official levels
  carry `derived_from_official_levels` quality metadata.

## Validation checkpoint

- Migration: fresh → head, 0004 → head, 0005 → head and a real-runtime copy all
  reach `0008_thesis_book`; the four consensus parent-mode mismatches are
  reclassified in place and not deleted.
- The real local database was backed up to
  `.runtime/backups/worldstate-pre-v06-20260809-191521.db` before upgrade.
  Its 10,132 legacy FRED demo observations are now explicitly `fixture`.
- Ruff and strict mypy: green across 92 checked source/test files.
- Pytest: current local suite is 178 passed with one dependency deprecation
  warning.
- Terminal UI production build: passed; npm audit reported 0 vulnerabilities.
- Rust/Tauri: fmt/check passed, 4 tests passed, unsigned no-bundle release built.
- Public-source smoke: BLS public API normalized 70 CPI and 106 NFP observations
  for 2023–2024; Federal Reserve 2025 calendar resolved to 8 active meetings.
- FOMC correction replay: the false 2025-08-22 event is soft-invalidated,
  2025-06-18 is 4.25–4.50 and 2025-10-29 is 3.75–4.00; stale values remain
  traceable as superseded.
- Missing-key behavior: FRED, Trading Economics and Databento report
  `not_configured`; no paid download was attempted. BLS schedule HTTP 403 is an
  explicit blocked ProviderRun and produces partial/non-zero sync status.
- GitHub Actions: the last recorded green run predates the current v0.7
  coverage checkpoint; after pushing this checkpoint, re-check PR #10 rather
  than treating the old run as current evidence. PR #10 remains Draft/open.

Do not reuse v0.4 pass counts as v0.5/v0.6 evidence.

## Next work after v0.6 checkpoint

1. Populate a bounded observed FRED/BLS/Fed dataset and verify the new World
   State/Daily Brief outputs against official release artifacts.
2. With legally usable credentials, validate FRED/ALFRED and Trading Economics
   PIT semantics and Databento estimates/entitlements against real accounts.
3. Add observed country catalogs only when official sources and availability
   timestamps are preserved; do not turn the global scaffolding into labels.
4. Add calendar-driven revision cards and deeper market reaction coverage after
   the observed data foundation is populated.

Do not add new event types, workspaces, automatic trading, news walls or maps in
this stabilization scope.

## Non-negotiable boundaries

Do not call correlation unique causation. Do not hide proxy, fixture, manual,
delayed, contaminated or missing data. Never mix fixture into observed coverage.
AI only summarizes a validated EvidencePack. Never commit credentials, account
data or proprietary raw payloads.
