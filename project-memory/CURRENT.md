# CURRENT — WorldState Macro Research Terminal

Updated: 2026-09-08

## Active product restructuring checkpoint (read first)

The user wants a complete usable workflow, not a cosmetic dashboard revision. Work is ongoing; do not mark the full product goal complete yet.

- Baseline was `f30ae84f4a834fce9f1b386f73cfadd413af4016`, branch remains `feature/v0.7-terminal-rebuild`.
- Implemented four primary entries: 雷达 / 事件台 / 市场脉络 / 研究记忆. Radar couples selected markets with explicitly conditional pathways and cross-asset checks; Data/Methods are in tools. Old TodayBoard is removed, underlying APIs retained.
- Added versioned observed-only display cache, independent reads, background refresh, offline preservation, hash/back navigation and event-response race guards. Do not reuse display cache as research input.
- CPI now shows expected/actual/surprise/revision side by side; existing import dialogs retained. Added pre-release observation guides and validated-claim/history reading in the event workflow.
- Local checks: backend 221 passed, Ruff/mypy passed; UI build, 10 policy tests and browser E2E passed; Rust fmt/check and eight tests passed. Production-like desktop build succeeded and actual Windows Radar/CPI/Markets/Macro were inspected. A final rebuild is needed after the last reading/market layout edits, followed by Data Sources/Research desktop checks and checkpoint/push.
- Build resource list no longer recursively includes the entire backend work directory (which failed on `.pytest_cache` access); source/migrations/config and frozen sidecar are explicit.
- Real runtime remains `.runtime/worldstate.db`. Market data is still dated August, no new minute imports or CPI AnalysisRun. Do not claim live market intelligence. No Consensus or Release changes, no Databento download in this restructuring.
- Detail: `docs/product/intelligence-workflow.md`. E2E runs a disposable browser with synthetic intercepted API responses; this does not prove live provider access.

September 8 continuation: the event interpretation tab now submits the existing analysis endpoint when readiness allows it, with a stable idempotency key and visible failure/retry. Browser regression verifies the submission, a simulated 503, retry identity and reading the completed validated claims. No live analysis was submitted. UI build, 10 policy tests and all browser smoke scenarios passed again. The tests intercept every API request in an isolated context, including the new write test; they never write to the runtime database.

Remaining: finish final desktop rebuild/verification and checkpoint push; review daily data activation within existing providers without expanding scope; retain the explicit minute-data blocker. PRs remain unmerged.

## Product truth

WorldState is a personal macro research and trading-assistance terminal. Its
daily job is to answer: what was released, how it differed from consensus, how
cross-assets reacted, what historical analogues show, and how confident an
evidence-bounded explanation should be.

World Monitor's news wall, world map and geopolitical-monitoring modules are no
longer part of the active architecture. Their final state is preserved at tag
`world-monitor-legacy-freeze` and branch `archive/world-monitor-legacy`.

## Active branch and milestones

- Working branch: `feature/v0.7-terminal-rebuild` (stacked on `feature/v0.7-live-global`)
- Last committed v0.4 baseline: `16544c373bb32fc9788b72538db49c3fcc2c1337`
- v0.5 Data Foundation: committed as `4054a66e620db2f5aff9a4c70b6af9be3b9aad94`; local and GitHub CI validation complete
- Database head in the worktree: `0010_operational_state_defaults`
- API contract: `/v2`
- Product version in the worktree: `0.7.0`
- Product code checkpoints: `c04c1ef` (event workflow), `16621c5` (global observed depth), `a97385f` (interactive daily markets), `ecfc7c7` (country/dimension drill-down and durable deep links) and `a1770ab` (focused Product API, contextual learning and verified Windows sidecar pipeline). PR #11 remains Draft.
- Runtime checkpoint: database migrated to `0010_operational_state_defaults`; the local runtime currently contains 148,331 observed macro rows across 70 populated series and 49,832 observed daily/context market bars across 19 instruments. Of those market rows, 5,802 are explicitly WorldState-derived 2s10s/3m10y curve observations. The runtime still has one observed world-state snapshot, zero observed consensus snapshots, zero observed minute bars and zero observed completed AnalysisRuns. Repeated current-public captures can produce more storage rows than unique period observations; product state selects one latest-known row per period at the requested `as_of`.
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

### 2026-08-12 public BLS calendar activation checkpoint

- The BLS adapter now prefers the official public `bls.ics` calendar (no BLS
  API key required) and falls back to the official release HTML.  Calendar
  artifacts record the provider, official status, retrieval hash, and any
  fallback source; current-year event titles supply the reference period rather
  than deriving it from the publication month.
- The parser and sync path are covered by 31 targeted tests, with Ruff and
  strict mypy passing.  A real runtime sync was attempted for the 2026-08-12
  CPI window.  This network returned HTTP 403 for both official BLS calendar
  endpoints, so the run is honestly `blocked` and no observed CPI release was
  created.  This is an external access restriction, not a missing BLS API key.
- No manual release, consensus snapshot, analysis run, or market download was
  created.  The official schedule page independently confirms CPI for July
  2026 at 08:30 America/New_York (12:30 UTC), but it was not persisted as an
  observed release because manual import is intentionally prohibited.
- After the HTTP path remained blocked, a controlled browser captured the
  official BLS August schedule page.  The capture created one observed
  `us_cpi-2026-07-observed` release at `2026-08-12T12:30Z`, with a durable
  artifact hash and `browser_capture` provenance; replaying it is idempotent.
  Four pre-T0 Trading Economics browser rows (headline/core MoM/YoY) were
  saved as observed consensus.  `Forecast` is stored as survey consensus and
  `TEForecast` remains a separate proprietary field; this path does not claim
  TE API access or entitlement.
- All automated BLS requests now use the stable contactable identity
  `WorldStateTerminal/0.7 (+https://github.com/631231771-cmd/worldstate-terminal)`.
  A single low-frequency verification of both endpoints at 03:57 UTC still
  returned HTTP 403; no retry loop was used.
- PRE-T0 correctness preflight is complete.  Actual readiness now uses the
  canonical analysis value selector and accepts a true initial actual captured
  after T0 while excluding unreconstructable current-version historical rows.
  Consensus rows are evaluated by `consensus-eligibility-v1`; the four CPI
  browser-captured rows are eligible with explicit D-quality/browser
  limitations.  Every release-linked one-minute manifest is checked without
  asset-list bypass.  Runtime CPI readiness remains correctly not ready:
  actual values and minute manifests are still absent.  No values, consensus
  timestamps, AnalysisRun, or Databento data were changed.

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

## v0.7 Terminal Rebuild (in progress)

- Checkpoint `654197a` adds a capability-driven product projection at
  `/v2/product/today` and a dataset inventory at `/v2/data/capabilities`.
- Today, Markets, Macro and Events now use a compact terminal shell with typed
  product models, drawers, command search, Learning/Advanced toggles,
  capability-aware empty states and valid-session market changes.
- Data Sources now exposes the capability inventory and an event-minute CSV
  import entry point. Minute event research remains unavailable until a legal,
  verified file is imported; no fixture bars are promoted to observed data.
- The rebuild is intentionally stacked on the live-global branch. It has not
  changed PR #10 status and has not merged any existing PR.
- PR #11 CI run `31365337023` is green across research-api, terminal-ui and
  desktop-check (the Windows no-bundle build took about ten minutes).
  and the data-control page was read in the running browser against the v0.7
  API. HICP correctly displayed `STALE` based on covered period age.

Detailed v0.7 evidence and limits are in
[`docs/macro/v0.7-live-global.md`](../docs/macro/v0.7-live-global.md).

## v0.7 Terminal Rebuild — current working checkpoint (2026-08-11)

- Product projections are now the source for the Today, Markets, Macro and
  Events workspaces. The API exposes typed `/v2/product/*` responses and a
  release detail projection; event ordering is server-defined (recent
  completed/reproducible first, then recent releases, then upcoming events).
- Market horizons are returned with explicit units: rates use basis points and
  price-like instruments use percentages. The frontend does not recompute
  financial changes from raw values.
- Product requests are loaded by active workspace, keeping the SQLite pool from
  being exhausted by five heavyweight projections during every navigation.
- The public FRED catalog now has observed China CPI, China industrial
  production, Japan CPI and Japan industrial production rows. The China OECD
  industrial-production export is already a same-period-prior-year index and
  is therefore stored as a level, not transformed a second time.
- Local runtime evidence after the public sync: China CPI 124 rows through
  2025-04, China industrial production 107 rows through 2023-11, Japan CPI 78
  rows through 2021-06, and Japan industrial production 111 rows through
  2024-03. These are current-public FRED observations, not PIT vintages; the
  Japan CPI and China industrial-production series are stale by covered-period
  age and are shown as such.
- Event detail supports a typed release projection and a consensus-entry modal.
  It now presents one continuous Overview → Expectations → Actual/Revision →
  Surprise → Market Reaction → Cross Asset → Historical Context →
  Interpretation → Evidence workflow.
- Consensus supports canonical indicator choices plus preview-first CSV import;
  post-T0 and unknown-indicator rows are reported and excluded from Surprise.
- The minute import wizard normalizes user-selected columns and timezone to UTC,
  reports duplicates/gaps/T0 coverage, and classifies each file as eligible,
  partial or ineligible. Only eligible release-linked manifests enter the Event
  Engine. Fixture files remain usable only inside fixture demonstrations and
  cannot enter observed research.
- Minute event reaction remains unavailable in the real runtime until a legal,
  verified eligible file is imported; daily context bars are never promoted to
  event windows. Current observed minute bars and observed consensus remain 0.
- Validation for this checkpoint: backend suite 190 passed; targeted product
  projection/import tests, Ruff, strict mypy and the Terminal UI production
  build pass. The 1920×1080 browser smoke covered the split Events workflow,
  Consensus modal, minute wizard and Events → Markets action with no console
  errors. PR #11 remains Draft and has not been merged.

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
- PR #10 CI run `31359986475` is green for this checkpoint: Research API,
  Terminal UI and Windows desktop/Tauri checks all passed; the PR remains Draft.

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
- A frozen Python sidecar directory now builds and passes migration/health
  smoke, but Tauri does not yet bundle or select it; the current desktop build
  is not a standalone signed installer for a blank computer.
- In a no-key observed database, World State, Daily Brief market confirmation,
  Series Explorer and global country cards can still be partial. The UI
  displays those gaps rather than substituting demo rows; current FRED context
  is not a replacement for licensed minute/event data.
- The global layer now has locally observed current-public history for USA,
  China, Japan, the euro area and the UK. China has growth/inflation/credit;
  Japan has growth/inflation/policy/liquidity; the euro area has
  growth/inflation/liquidity/external; and the UK has growth/inflation/policy.
  China and Japan are marked stale because important component series end well
  before the current date. These FRED graph histories are non-PIT and do not
  replace official national first-print/vintage or event-window data.

- Global state loading selects one latest-known observation for each period at
  the requested `as_of`; repeated retrieval vintages no longer inflate signal
  history. Freshness is calculated from the covered period against the requested
  `as_of`, not from the fetch timestamp or today's date. FRED catalog sync also
  preserves USA/China/Japan/euro-area/UK entity ownership instead of assigning
  all catalog series to USA.

- The daily market board has 19 locally populated assets: 3M/2Y/5Y/10Y/30Y
  Treasury yields, 10Y real yield, 2s10s and 3m10y curves, broad USD,
  EUR/USD, USD/JPY, USD/CNY, S&P 500, Nasdaq-100, gold, WTI, Brent, VIX and
  U.S. high-yield spread. Public FRED rows remain daily context/non-PIT. Curve
  bars are calculated locally from matched observed input dates and persist
  input bar IDs, formula, calculation version and calculated-at metadata.
  Market change and chart paths use only the newest compatible continuity
  segment; provider/identity changes or large gaps are not silently joined.

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
- GitHub Actions: PR #10 run `31359986475` passed all three jobs after the
  productization checkpoint. PR #10 remains Draft/open.

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

## Country research and deep-link checkpoint (2026-08-11)

- `/v2/product/macro/{country}` is an on-demand country projection built from
  the existing PIT-aware global state pipeline. It returns the selected
  dimension, observed driver series, related daily markets, same-dimension
  country comparison, event context and explicit limitations.
- World State history is never synthesized. Existing immutable daily snapshots
  are exposed only for the US World State; China, Japan, the euro area and the
  UK explicitly report that independent country snapshots are unavailable.
- The Macro matrix retains missing cells, excludes unavailable countries from
  comparisons, and presents relative divergence as context rather than causal
  attribution.
- Product URLs now restore concrete research context after refresh:
  `#markets?asset=...`, `#macro?country=...&dimension=...`,
  `#macro?series=...`, `#events?release=...` and `#research?thesis=...`.
- Ctrl+K searches actual markets, Series, releases, countries and Theses. Live
  browser smoke verified Gold, China CPI, the China/inflation country view and
  a concrete FOMC release.

## Product architecture and sidecar checkpoint (2026-08-11)

- Stable `/v2/product/*` routes now live in `api/v2/product_router.py`; the
  top-level v2 router only includes that focused router and all URLs remain
  compatible. The Terminal UI similarly separates shared transport from the
  Product API while older clients migrate gradually.
- Learning Mode now uses a concise 12-item concept registry for macro states,
  rates, risk and event research. Explanations appear only when Learning Mode
  is enabled and stay contextual rather than becoming encyclopedia pages.
- Today now renders state directions, focus changes, market freshness, country
  coverage and actionable empty states in product Chinese. Provider/context
  labels remain available in Data Details but no longer leak into the first
  screen.
- `scripts/build-research-sidecar.ps1` reproducibly creates a PyInstaller
  onedir Research API for Windows. A clean-database migration and independent
  `/v2/health` smoke pass without system Python. The verified folder contains
  1,028 files / 75.2 MB and a 16.6 MB launcher.
- CI now builds, smokes and uploads the Windows sidecar artifact. Release Tauri
  resources select this sidecar when the generated artifact is present; the
  current development EXE remains Python-backed.

## v0.7 beta closure / event correctness (2026-08-11)

- `41b105d` adds a shared `AnalysisReadiness` gate and explicit
  `event-intraday-v1` manifest policy. Observed analysis cannot create a
  completed run unless canonical Actual/Consensus pairs, pre-T0 consensus and
  at least one eligible event-minute manifest are present. The API exposes
  `/v2/releases/{release_id}/analysis-readiness` and returns structured 409
  blockers when the gate is not satisfied.
- Legacy minute manifests without eligibility metadata are rejected for
  canonical event instruments. Fixture manifests are explicitly fixture
  policy-labelled. Missing key minute windows are reported per-window and
  incomplete short windows no longer receive a complete reaction value.
- `6f1e875` makes consensus T0 checks stage-aware and timezone-normalized;
  FOMC uses the statement stage as the primary T0. Treasury futures proxies
  remain percentage-price reactions; only cash-yield reactions use bp.
- `35034a0` and `fb442d0` produce a repo-independent PyInstaller sidecar smoke
  (fresh migration plus `/v2/health` and all four product endpoints). Release
  Tauri resources select the bundled sidecar when present; development builds
  retain the Python source path. The executable is a generated build artifact,
  not source-controlled.
- Local verification: 203 backend tests, Ruff and strict mypy pass; Tauri
  fmt/check/tests and the no-bundle desktop build pass. Runtime truth remains
  unchanged: observed minute bars and observed consensus are zero, so there is
  no observed real-event AnalysisRun yet. CPI/NFP/FOMC examples remain fixture
  demonstrations until legal verified minute and pre-T0 consensus data are
  imported.

## First observed CPI chain checkpoint (2026-08-13)

- Release `145dd1f1-55de-43df-8b87-66c9ef848c7c` is the observed US CPI
  release for 2026-07 at `2026-08-12T12:30:00Z`. The official BLS current-data
  sync now marks a matched calendar release and its release stage as released.
- Four pre-T0 Trading Economics survey-consensus snapshots are present and
  eligible: headline MoM 0.1, headline YoY 3.4, core MoM 0.2 and core YoY 2.5.
  They remain quality D browser captures with explicit source-semantics and
  provenance limitations; they are not provider-API captures.
- Four observed BLS Actual values are present: headline MoM 0.1, headline YoY
  3.3, core MoM 0.2 and core YoY 2.5. The public BLS API disabled server-side
  calculations, so deterministic percentage derivations from official level
  observations retain that limitation in metadata.
- Consensus eligibility now has one canonical policy shared by readiness,
  analysis input selection and coverage. Approved quality A/B/C rows retain
  legacy eligibility with explicit provenance/semantics limitations; quality D
  requires the stronger browser-capture provenance and semantics checks.
- Product Event detail now exposes the four Actual/Consensus pairs and their
  individual raw and threshold-scaled surprises even before an AnalysisRun.
  True surprise Z-scores remain null because no qualifying 20-sample PIT error
  history exists.
- `AnalysisReadiness` is intentionally still blocked only by
  `missing_eligible_event_minute_manifest`; no observed AnalysisRun has been
  created. Databento historical GLBX.MDP3 and OHLCV-1m were verified in the
  signed-in catalog, but `DATABENTO_API_KEY` is not configured locally and no
  data was purchased or downloaded.
- Current verification: 221 backend tests pass, Ruff and strict mypy pass, and
  the Terminal UI production build passes. Browser smoke confirmed the Events
  page shows the CPI release as released, four expectations, four Actuals,
  bounded Surprise output and the actionable missing-minute-data state.
