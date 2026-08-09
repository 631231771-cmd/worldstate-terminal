# CURRENT — WorldState Macro Research Terminal

Updated: 2026-08-09

## Product truth

WorldState is a personal macro research and trading-assistance terminal. Its
daily job is to answer: what was released, how it differed from consensus, how
cross-assets reacted, what historical analogues show, and how confident an
evidence-bounded explanation should be.

World Monitor's news wall, world map and geopolitical-monitoring modules are no
longer part of the active architecture. Their final state is preserved at tag
`world-monitor-legacy-freeze` and branch `archive/world-monitor-legacy`.

## Active branch and milestones

- Working branch: `refactor/macro-research-terminal`
- Last committed v0.4 baseline: `16544c373bb32fc9788b72538db49c3fcc2c1337`
- v0.5 Data Foundation: committed as `4054a66e620db2f5aff9a4c70b6af9be3b9aad94`; local and GitHub CI validation complete
- Database head in the worktree: `0007_truthfulness_stabilization`
- API contract: `/v2`
- Product version in the worktree: `0.5.0`
- PR #8: Draft, unmerged; do not mark Ready or merge before final validation

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

## Honest incomplete boundaries

- Sync commands and reconciliation are wired and return honest
  `completed`/`partial`/`blocked` results. The backfill worker consumes approved
  jobs, retains partial results and cannot bypass paid-data gates.
- The validation environment has no FRED, Trading Economics or Databento key.
  Those are the credential blockers; TE historical replay additionally requires
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

## Validation checkpoint

- Migration: fresh → head, 0004 → head, 0005 → head and a real-runtime copy all
  must reach `0007_truthfulness_stabilization`; the four consensus parent-mode
  mismatches are reclassified in place and not deleted.
- The real local database was backed up to
  `.runtime/backups/worldstate-pre-v05-final-20260802-2135.db` before upgrade.
  Its 10,132 legacy FRED demo observations are now explicitly `fixture`.
- Ruff and strict mypy: green across 92 checked source/test files.
- Pytest: the v0.5.1 validation run is authoritative; do not reuse the previous count.
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
- GitHub Actions: use the latest run for the current pushed PR head; historical
  commit/run references are not proof for v0.5.1. PR #8 remains Draft and unmerged.

Do not reuse v0.4 pass counts as v0.5 evidence.

## Next work after this stabilization only

1. Re-run BLS schedule ingestion from a network where the official HTML is not
   blocked, and preserve the resulting artifact.
2. With legally usable credentials, validate FRED/ALFRED and Trading Economics
   PIT semantics and Databento estimates/entitlements against real accounts.
3. Perform a bounded approved real-data backfill and assess stored versus
   analysis-eligible coverage gaps.

Do not add new event types, workspaces, automatic trading, news walls or maps in
this stabilization scope.

## Non-negotiable boundaries

Do not call correlation unique causation. Do not hide proxy, fixture, manual,
delayed, contaminated or missing data. Never mix fixture into observed coverage.
AI only summarizes a validated EvidencePack. Never commit credentials, account
data or proprietary raw payloads.
