# Data providers

WorldState owns the domain model. Provider-specific schemas stop at
`provider_kit`; normalized release, consensus, calendar, market-bar and source
artifact records are the only contracts exposed to the rest of the system.

## Capability status

| Provider/path | Adapter | Persistence orchestration | Live validation in this v0.5 worktree |
| --- | --- | --- | --- |
| Manual release/consensus | Implemented | Implemented | Available locally |
| CSV minute bars | Implemented | Implemented | Fixture/manual workflows covered by existing tests |
| Fixture provider | Implemented | Implemented, isolated as `fixture` | End-to-end CPI/NFP/FOMC demonstrations |
| BLS Public Data API | Implemented for CPI/NFP series and release schedules | Wired to append-only official/calendar sync | No key required in public mode; schedule HTML returned HTTP 403 on this validation network; current API cannot reconstruct old first prints |
| Federal Reserve | Implemented for FOMC calendar/material parsing | Wired for 2015–2020 archives and current/future scheduled meetings/stages | Public source was reachable in validation; unverified `key_qa`/`press_end` times remain absent |
| FRED/ALFRED | Implemented for observations, realtime periods and vintages | Wired to official sync and PIT persistence | Blocked in this environment by missing FRED API key |
| Trading Economics | Implemented for calendar/consensus/PIT semantics | Wired to snapshots, quota/entitlement, artifacts and Official-vs-TE reconciliation | Current fetch blocked by missing key; historical replay also requires PIT entitlement |
| Databento | Implemented for symbology, cost estimate and OHLCV adaptation | Wired to event-linked manifests, bars, integrity checks and recoverable worker | Blocked by missing key/entitlement and paid-data gates; no paid download was run |

“Implemented adapter” means typed request/response handling, source artifact
metadata, explicit errors and deterministic mocked-response tests exist. It does
not mean a licensed historical dataset has been downloaded. Sync commands now
populate durable records when upstream access is available.

## Unified contracts

Provider capabilities expose source terms, rate limits, timeout/retry policy,
supported operations and data semantics without exposing credentials. Provider
runs and artifacts record:

- provider and operation;
- idempotency key and status;
- request/record counts;
- quality grade and warnings;
- estimated/actual cost when known;
- source URL, retrieval/publication time, content type, byte length and hash;
- `observed` or `fixture` data mode;
- entitlement, quota and licence references.

Raw payload bytes may be retained locally for reproducibility. They are not
returned by provider-status endpoints and must not be committed when the source
licence or account terms prohibit redistribution.

## Failure and fallback policy

- Missing credentials return `not_configured`; they never trigger an implicit
  fixture fallback in an observed run.
- Entitlement, quota, schema, point-in-time, rate-limit and transport failures
  remain typed provider errors.
- A provider failure cannot silently change an instrument into a proxy.
- `observed` only describes the data mode. It does not by itself mean verified,
  complete, first-release or grade A.
- Fixture and observed records can coexist for the same event/time because their
  database identities include `data_mode`, but analyses and coverage queries do
  not mix them.

## Current command boundary

`data-doctor`, `data-status` and `estimate-backfill` expose safe diagnostic
information. `sync-official`, `sync-calendar`, `snapshot-consensus`,
`sync-market` and `reconcile-data` call durable services and distinguish
`completed`, `partial` and `blocked`. A non-blocking scheduler and recoverable
worker run while the API is open. Missing FRED/TE/Databento keys, TE PIT
entitlement for replay, or Databento rights/paid-data gates remain honest
blockers; none causes a fixture fallback.

Provider health is not a hidden paid probe. TE daily health records
`configured_unverified` with zero network/request count. A completed data sync,
with its artifact and quota, is the live-health evidence.

Provider-specific details:

- [Official providers](official-providers.md)
- [Trading Economics](trading-economics.md)
- [Databento](databento.md)
- [Backfill cost controls](backfill-cost-control.md)
- [Data reconciliation](data-reconciliation.md)
