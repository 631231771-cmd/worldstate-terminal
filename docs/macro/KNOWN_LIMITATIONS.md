# Known limitations

## CPI Event Lab limits

- The February 2024 actual CPI values and archived consensus source are
  traceable, but bundled GC/SI/DXY/ES/NQ/ZT/ZN minute bars are deterministic
  fixtures. They prove the workflow and are not historical exchange records.
- ZT and ZN are Treasury-futures prices used as directional yield proxies.
  They are never displayed as cash 2-year or 10-year yields.
- The minute-bar detector reports the earliest **observed** significant,
  consecutively confirmed response. It cannot establish ordering within one
  bar or replace tick data.
- U.S. cash close, next close, and five-trading-day windows remain incomplete
  until a CSV/provider supplies session-aware coverage. Partial results carry a
  missing/coverage flag.
- The first historical set is small. Probability and percentile output appears
  only when a fixed, declared filter retains at least five observations;
  otherwise the API exposes case studies without statistical claims.
- Consensus is not freely and reliably available from one official source.
  Manual, CSV, and replaceable provider entry are supported and permanently
  timestamped, but operator verification remains necessary.
- Contamination detection includes registered overlapping events and notes. It
  cannot guarantee that every contemporaneous headline, positioning flow, or
  private order was observed.
- Deterministic rules compare multiple explanations. They do not prove unique
  causality. An AI layer may summarize these structured results but must not add
  missing facts.
- Automatic BLS/BEA/Fed release ingestion, licensed minute feeds, nonfarm
  payroll bundles, and multi-stage FOMC analysis are subsequent slices.

## Phase 3 world-explanation limits

- Free news and market endpoints can be delayed, rate-limited, regionally
  unavailable, or incomplete. The API reports `PARTIAL` rather than presenting
  missing evidence as complete.
- The market layer uses daily public quotes, not tick-level exchange feeds.
  It supports event-after-the-fact learning, not millisecond attribution.
- The deterministic event ranker and causal playbooks identify plausible
  transmission mechanisms. They do not prove causality.
- Public data does not reveal complete institutional order flow, private fund
  positioning, dealer books, or every options hedge. The UI explicitly marks
  that unknown instead of naming a buyer without evidence.
- Keyless explanations are rules-based. Rich natural-language follow-up
  requires a local Ollama model or a separately billed cloud-model API key.
- News titles may remain in the publisher's original language. The interface
  adds a Chinese learning title and explanation without pretending to be a
  verbatim translation.
- The five-minute server cache deliberately favors stable daily research over
  continuous streaming. `fresh=true` bypasses it for manual refresh.
- Market explanations are educational hypotheses and not investment advice,
  price targets, or automated trading signals.

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
