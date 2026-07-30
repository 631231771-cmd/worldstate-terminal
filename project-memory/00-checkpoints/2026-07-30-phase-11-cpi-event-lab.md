---
project: World State Terminal
phase: 11
date: 2026-07-30
status: complete
implementation_commit: 2984f7e1e
open_source_audit_commit: 79cf4d371
next_phase: nonfarm-payroll-event-bundle
---

# Phase 11 checkpoint — US CPI Event Lab

## Outcome

World State Terminal now has a complete, locally runnable CPI event-research
slice rather than a static macro dashboard. It accepts point-in-time CPI
release and consensus data, imports minute bars, calculates multi-window
cross-asset reactions, separates facts from hypotheses, compares a declared
historical sample, penalizes event contamination, and renders a readable
event-review report.

## Open-source adoption decision

- OpenTerminalUI: provider and terminal architecture reference; WorldState
  independently implemented its narrow contracts and components.
- Macrosynergy: optional Python dependency behind a WorldState adapter.
- OpenBB: future isolated provider only; it is not required at runtime.
- Fincept Terminal: product research only; no code, UI, or visual identity was
  copied.
- Exact inspected commits, licenses, candidate files, and decisions are in
  `docs/macro/open-source-adoption.md`.
- `THIRD_PARTY_NOTICES.md` records notices and licensing boundaries.

## Domain and storage

Alembic revision `0002_cpi_event_lab` adds:

- macro events;
- event indicators;
- append-only consensus snapshots;
- market instruments and bars;
- event-window metrics;
- event analyses;
- unified data-quality records.

The data-quality model records source, retrieval time, manual and verification
state, fixture and proxy state, delay, granularity, missing reason, quality
grade, and notes.

## CPI bundle

The bundle supports:

- headline CPI MoM;
- headline CPI YoY;
- core CPI MoM;
- core CPI YoY;
- previous and revised-previous values;
- raw, relative, and standardized surprise;
- component direction and combined classification;
- headline/core and MoM/YoY conflicts;
- revision-dominant classification.

## Market analysis

- Instruments: GC, SI, DXY, ES, NQ, ZT, and ZN.
- ZT and ZN are visibly marked price proxies for yield direction.
- Providers: CSV, deterministic fixture, and ordered waterfall.
- Windows: T-60, T-15, T+1/5/15/30/60, T+4h, same-day close, next-day close,
  and day 5.
- Metrics: return/change, maximum rise/fall, volatility, volume change,
  spike-fade, dip-recovery, and direction reversal.
- Earliest reaction is explicitly an earliest observed minute-level reaction;
  it uses a volatility/MAD baseline, minimum instrument threshold, and two-bar
  confirmation.
- Incomplete windows preserve coverage and missing reasons instead of
  extrapolating.

## Explanation and history

- Deterministic facts are calculated before interpretation.
- Rules can produce more than one plausible transmission path.
- Competition and unknowns remain visible.
- Pollution records overlapping events, contamination level, confounding
  notes, and clean-window state.
- Contamination lowers confidence and removes strong causal language.
- Historical matching has one declared recipe, reports counts before and after
  filtering, and requires five retained observations for probabilities and
  percentiles.
- The natural-language report is generated only from structured results.

## API and frontend

API:

- `GET /v1/events/lab/status`
- `GET /v1/events?event_type=US_CPI`
- `GET /v1/events/{event_id}`
- `POST /v1/events/cpi`
- `POST /v1/events/{event_id}/consensus`
- `POST /v1/events/{event_id}/market-bars/import`
- `POST /v1/events/{event_id}/analyze`

Frontend:

- historical event archive;
- four CPI indicator cards;
- normalized seven-asset event chart;
- multi-window reaction table;
- first-observed reaction and granularity limit;
- reversal state;
- fact, main-rule, and competing-explanation columns;
- historical recipe, counts, metrics, and reliability;
- contamination, data quality, provenance, gaps, confidence, and review report.

## Historical demonstration

Primary demonstration:

- Release: US CPI, 2024-02-13, 08:30 America/New_York.
- Actual: headline 0.3% MoM / 3.1% YoY; core 0.4% MoM / 3.9% YoY.
- Archived consensus: 0.2% / 2.9% / 0.3% / 3.7%.
- Previous revision: December headline MoM revised from 0.3% to 0.2%.
- Combined classification: `全面偏热`.
- Historical mode: statistics.
- Fixed-recipe retained sample: 5 events.
- Explanation confidence: 0.55.

The actual release comes from the archived BLS release. The consensus source is
stored separately. The bundled cross-asset minute path is a deterministic
fixture and is labelled as such throughout storage, API, and UI. It is not
presented as a verified exchange record.

Runtime demonstration store:

- 9 CPI events;
- 18,963 minute bars;
- 693 window metrics;
- 9 event analyses.

## Verification

- Backend: 58 tests passed at 85.43% coverage.
- Clean SQLite migration and demo seed: passed.
- PostgreSQL offline migration SQL: passed.
- Ruff: passed.
- Strict mypy: passed.
- TypeScript typecheck: passed.
- Focused Biome check: passed.
- Safe-HTML guard: passed.
- Markdown lint: passed.
- Macro production build: passed.
- Launcher status: API and frontend healthy.
- Desktop browser layout: passed.
- 430-pixel browser layout: passed with no document-level horizontal overflow.
- Rendered audit: four indicator cards, seven asset rows, seven historical
  metric cards.

## How to open

Run `WorldStateApp.bat`, or run `WorldState.bat start` and open:

`http://127.0.0.1:4173/?lang=zh&view=lab&labEvent=0525dad4-8d45-45ed-8e76-f47d22f3ad90`

## Known boundaries

- Included market bars and most comparison cases are fixtures.
- Full exchange history, tick precedence, and causal identification are outside
  the claim of the current slice.
- Long-horizon metrics remain missing without sufficient imported sessions.
- Automatic consensus ingestion is not bundled.
- Automatic news contamination detection is incomplete.
- Futures rolls, holiday-aware continuous contracts, and verified real-yield
  minute data need a future market provider.

## Resume instructions

Start Phase 12 with the nonfarm-payroll event bundle. Reuse the existing event,
indicator, consensus, quality, provider, window, contamination, history, and
explanation primitives. Add payroll growth, unemployment, average hourly
earnings, participation, and revisions without weakening current provenance or
minimum-sample safeguards. Then extend the same framework to multi-stage FOMC.
