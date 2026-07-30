---
project: World State Terminal
status: phase-11-cpi-event-lab-complete
updated: 2026-07-30
branch: feature/world-state-terminal
phase_1_formal_commit: a458e54d06b32992001693804b49f5f59a1f4019
phase_2_formal_commit: d144c96a6afcf674e854e80feefbfa66cdbf8549
phase_3_formal_commit: 3ca562b1264db05beb5bf94dfd819b419bee5263
phase_4_desktop_chain_commit: 1e9327e6f542a4224f3532b6452f8b4e094b2b84
phase_5_research_seminar_commit: 86b48c2397d5152d9e7d7304cfca9f40c73090d5
phase_6_clawfeed_webmcp_commit: 63b380e3b
phase_7_agent_reach_commit: c86554868
phase_8_research_desk_commit: ff6cd0be22232661bb9ed0d06bad29d48a447809
phase_9_event_reaction_commit: 0864f26ec40efc506f8731dcf439f28008ddb696
phase_10_research_journal_commit: 93adf9169a97e3b021f1c7110dd3fdab97cad9a3
phase_11_open_source_audit_commit: 79cf4d371
phase_11_cpi_event_lab_commit: 2984f7e1e
resume_from: phase-12-nonfarm-payroll-event-bundle
---

# Current continuation point

> [!important] Resume here
> Phase 11 is complete. World State Terminal now has a running US CPI Event
> Lab that separates verified release values, pre-release consensus snapshots,
> illustrative or imported market bars, deterministic facts, competing macro
> explanations, historical comparison, contamination, and data limitations.
>
> Continue with the nonfarm-payroll bundle, then the multi-stage FOMC event
> model. Do not weaken the point-in-time, provenance, proxy-label, contamination,
> minimum-sample, or bounded-language rules added in Phase 11.

Completion checkpoint:
`00-checkpoints/2026-07-30-phase-11-cpi-event-lab.md`

## What is running

- `WorldStateApp.bat` opens the native desktop shell.
- `WorldState.bat` controls the API and frontend with `start`, `stop`,
  `restart`, `status`, `sync`, `doctor`, and `logs`.
- The API runs at `http://127.0.0.1:8000`.
- The frontend runs at `http://127.0.0.1:4173`.
- CPI Event Lab:
  `http://127.0.0.1:4173/?lang=zh&view=lab&labEvent=0525dad4-8d45-45ed-8e76-f47d22f3ad90`

## Product structure

The terminal has eight URL-backed workspaces:

1. `overview` — 今日桌面；
2. `events` — 事件雷达；
3. `calendar` — 事件研究工作台；
4. `lab` — CPI 事件实验室；
5. `markets` — 资产地图；
6. `themes` — 国家与主题；
7. `signals` — 观点与证据；
8. `library` — 学习、复盘与 AI 导师。

## Phase 11 delivered state

- CPI is an event bundle with headline/core MoM and YoY indicators.
- Each indicator stores actual, consensus, previous, revised previous, unit,
  source, capture time, version, and point-in-time metadata.
- Consensus snapshots are append-only and reject snapshots captured after the
  release time.
- Surprise analysis covers raw, relative, standardized, direction, composite
  classification, core/headline conflict, MoM/YoY conflict, and revisions.
- Market-data contracts support CSV, deterministic fixture, and ordered
  provider waterfall.
- Seven instruments are available: GC, SI, DXY, ES, NQ, ZT, and ZN.
- ZT and ZN are explicitly labelled Treasury-futures price proxies; they are
  never presented as direct yield observations.
- Event windows cover T-60, T-15, T+1/5/15/30/60, T+4h, same-day close,
  next-day close, and day 5, with missing coverage preserved.
- Earliest significant reaction uses pre-event volatility, normal-minute
  distribution, per-instrument floors, and two consecutive bars.
- Reversal, spike-fade, and dip-recovery require adequate window coverage.
- Historical matching declares the recipe, reports before/after counts, and
  needs at least five retained samples before probability or percentile output.
- Facts, historical rules, plausible inference, competing explanations, and
  unknowns remain separate in the report.
- Contamination reduces confidence and disables strong causal language.
- AI is not used to manufacture facts; the shipped report is deterministic.
- The Event Lab frontend includes an archive, surprise cards, normalized
  cross-asset chart, reaction table, explanation columns, history, quality,
  provenance, gaps, contamination, confidence, and a readable review report.

## Demonstration state

- Verified release: US CPI published on 2024-02-13 at 08:30 America/New_York.
- Official actuals: headline 0.3% MoM / 3.1% YoY and core 0.4% MoM / 3.9% YoY.
- Archived consensus: 0.2% / 2.9% / 0.3% / 3.7%.
- Classification: `全面偏热`.
- Runtime fixture store: 9 CPI events, 18,963 minute bars, 693 window metrics,
  and 9 analyses.
- Historical comparison retains 5 fixed-recipe samples and runs in statistics
  mode.
- Confidence is capped at 0.55 because bundled minute paths are labelled
  deterministic fixtures rather than verified exchange records.

## Verification

- Backend: 58 tests passed, 85.43% coverage.
- Ruff, strict mypy, TypeScript, focused Biome, safe-HTML guard: passed.
- Alembic clean migration through revision `0002`: passed for SQLite and
  PostgreSQL offline SQL generation.
- Macro production build: passed.
- Browser: desktop and 430-pixel mobile layouts passed with no document-level
  horizontal overflow.
- Runtime: API and frontend launcher services healthy.

## Important boundaries

- The bundled CPI actuals and consensus references are traceable; bundled
  market bars and most comparison cases remain clearly labelled fixtures.
- Minute bars support only “earliest observed significant reaction”, not
  exchange-level causal or order-flow precedence.
- Long-horizon windows remain missing until imported data covers the required
  session and future trading days.
- Consensus is currently manual/API/CSV-capable; no paid automatic consensus
  feed is bundled.
- Event pollution can be recorded and penalized, but automatic news-overlap
  detection is not yet comprehensive.
- Futures rollover, full holiday calendars, and verified session-aware
  continuous contracts remain future provider work.
- Macrosynergy is an optional adapter dependency. OpenBB is not required.
- OpenTerminalUI was used as an architecture reference only. Fincept source and
  visual identity were not copied.

## Key files

- Phase progress: `docs/macro/progress/phase-11-cpi-event-lab.md`
- Open-source audit: `docs/macro/open-source-adoption.md`
- Third-party notices: `THIRD_PARTY_NOTICES.md`
- Database models: `services/macro-engine/src/macro_engine/db/models.py`
- Migration: `services/macro-engine/migrations/versions/0002_cpi_event_lab.py`
- Event service: `services/macro-engine/src/macro_engine/event_lab/service.py`
- Surprise engine: `services/macro-engine/src/macro_engine/event_lab/surprise.py`
- Window engine: `services/macro-engine/src/macro_engine/event_lab/windows.py`
- Historical matcher: `services/macro-engine/src/macro_engine/event_lab/history.py`
- Explanation engine:
  `services/macro-engine/src/macro_engine/event_lab/explanation.py`
- Market providers:
  `services/macro-engine/src/macro_engine/market_data/providers.py`
- API: `services/macro-engine/src/macro_engine/api/events.py`
- Frontend: `src/macro/MacroApp.ts`
- Frontend styles: `src/macro/macro-terminal.css`

## Next priorities

1. Reuse EventBundle primitives for nonfarm payrolls: payroll growth,
   unemployment rate, average hourly earnings MoM/YoY, participation rate, and
   previous revisions.
2. Add FOMC stages for statement, press conference start, important Q&A, and
   end, with stage-specific reaction and changing explanations.
3. Import verified historical minute bars with session calendars, roll
   metadata, and real yield observations where licensing permits.
4. Add official-release ingestion, consensus snapshot workflow, contamination
   candidates, backfill, and scheduled analysis.
