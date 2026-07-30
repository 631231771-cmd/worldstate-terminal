# Phase 11: U.S. CPI Event Lab

Status: complete on 2026-07-30.

## Outcome

World State Terminal now has a runnable macro-event vertical slice rather than
only a daily-event explanation page. One CPI release is represented as a
simultaneous four-indicator bundle, linked to point-in-time consensus snapshots,
source-quality records, cross-asset minute bars, event windows, historical
comparisons, bounded competing explanations, and a readable report.

## Open-source adoption

The adoption decision is recorded in
[`../open-source-adoption.md`](../open-source-adoption.md).

- OpenTerminalUI informed the provider/failover/cache boundary. WorldState
  independently rewrote the narrow contracts; no source was copied.
- Macrosynergy is an optional BSD-3-Clause analytics dependency behind a
  WorldState adapter.
- OpenBB remains an optional, isolated future provider because its AGPL boundary
  adds little value to the first CSV/fixture slice.
- Fincept Terminal was used only for product research. No code, UI, or visual
  identity was copied.
- Root [`../../../THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md)
  records commits, licenses, decisions, and copyright obligations.

## Domain and persistence

Alembic revision `0002_cpi_event_lab` adds:

- `data_quality_records`;
- `macro_events`;
- `event_indicators`;
- `consensus_snapshots`;
- `market_instruments`;
- `market_bars`;
- `event_window_metrics`;
- `event_analyses`.

Consensus snapshots are append-only and must predate release. Actual,
consensus, previous, revised previous, first release, data version, source
timezone, and quality IDs are stored separately. A proxy instrument carries
both `is_proxy` and `proxy_for`.

## Calculation

- Headline CPI MoM/YoY and Core CPI MoM/YoY each receive raw, relative, and
  standardized surprise values.
- The bundle distinguishes all-hot, all-cold, core-led, headline/core conflict,
  monthly/annual conflict, in-line, and revision-dominant outcomes.
- Windows include pre-60/pre-15 and post-1/5/15/30/60/4h. Longer session windows
  are retained with explicit coverage/missing state until sufficient data is
  imported.
- Earliest reaction uses pre-event volatility, median absolute movement, a
  per-instrument floor, and two consecutive bars.
- Historical comparison uses one declared recipe. Direction and core direction
  are filters; magnitude and regime remain similarity-ranking inputs. At least
  five retained observations are required for probability and percentile.
- Explanation output keeps confirmed facts, historical rules, plausible
  inference, competition, and unconfirmed limits distinct.

## Data and providers

- One verified historical example uses the February 13, 2024 BLS CPI release.
- The archived consensus reference is stored separately from the official
  actual-value source.
- Seven instruments are supported: GC, SI, DXY, ES, NQ, ZT, and ZN.
- ZT and ZN are explicit futures-price proxies for yield direction.
- CSV, deterministic fixture, and ordered provider-waterfall implementations
  share the WorldState OHLCV contract.
- Historical cases and market bars included with the repository remain
  traceable fixtures unless explicitly verified.

## Product

The new `view=lab` workspace contains:

- a historical CPI event archive;
- large-format four-indicator surprise cards;
- normalized event-relative cross-asset SVG chart;
- multi-window reaction table;
- reversal, spike-fade, and dip-recovery states;
- first-observed reaction and granularity warning;
- fact/rule/competition reasoning columns;
- fixed-sample historical metrics and filters;
- report, confidence, contamination, quality, provenance, and data gaps.

## API

- `GET /v1/events/lab/status`
- `GET /v1/events?event_type=US_CPI`
- `GET /v1/events/{event_id}`
- `POST /v1/events/cpi`
- `POST /v1/events/{event_id}/consensus`
- `POST /v1/events/{event_id}/market-bars/import`
- `POST /v1/events/{event_id}/analyze`

Local desktop writes are loopback-only by default. Server writes require the
existing explicit enable flag and token.

## Demonstration result

The February 2024 event classifies as **全面偏热**:

- headline MoM 0.3 versus 0.2 consensus;
- headline YoY 3.1 versus 2.9;
- core MoM 0.4 versus 0.3;
- core YoY 3.9 versus 3.7;
- December headline MoM previous revised from 0.3 to 0.2.

The bundled illustrative market path produces the expected hot-inflation
cross-asset shape: Treasury-futures proxies and risk assets fall, the dollar
rises, and precious metals weaken after an initial silver reversal. The report
labels every market bar as fixture and caps confidence accordingly.

## Verification

- Alembic clean SQLite migration and full demo seed: pass.
- Demo contents: 9 CPI events, 18,963 minute bars, 693 window metrics, and 9
  analyses.
- Backend: 58 tests passed at 85.43% coverage.
- Ruff, strict mypy, TypeScript, focused Biome, safe-HTML guard: pass.
- Macro production build: pass.
- Launcher verification: both API and frontend services are healthy.
- Browser verification: desktop and 430-pixel mobile layouts pass; the page has
  no document-level horizontal overflow and renders four indicator cards,
  seven asset rows, and seven historical-statistic cards.

## Next slice

1. Import verified historical minute bars and session calendars.
2. Add the nonfarm-payroll indicator bundle.
3. Add multi-stage FOMC statement/press-conference windows.
4. Add automatic official release ingestion and background backfill.
