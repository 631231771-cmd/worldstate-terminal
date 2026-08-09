# Databento market data

`DatabentoMarketProvider` is the optional licensed historical-market adapter for
the fixed v0.5 asset set. It is not a bundled dataset and has not downloaded paid
data in the current no-key environment.

| Asset | Venue shown by WorldState | Databento dataset |
| --- | --- | --- |
| GC, SI | COMEX | `GLBX.MDP3` |
| CL | NYMEX | `GLBX.MDP3` |
| ES, NQ | CME | `GLBX.MDP3` |
| ZT, ZN | CBOT | `GLBX.MDP3` |
| DX | ICE Futures US | `IFUS.IMPACT` |
| VX | Cboe Futures Exchange | `XCBF.PITCH` |

The adapter supports symbology/continuous-contract resolution, provider/fallback
cost estimates and `ohlcv-1m` / `ohlcv-1d` response adaptation. Intraday research
requests target T-90 minutes through T+4 hours; longer outcomes use daily bars or
an explicit session-close rule rather than five days of minute data. If bars are
aggregated, the source schema, method and version must be recorded and the result
must not be labelled exchange-provided OHLCV.

Each persisted market manifest can retain event/stage, requested/resolved symbol,
instrument/contract, dates, continuous mapping, selection rule, roll state,
dataset/schema, interval, row count, source artifact and content hash. Bars from
different contracts are not silently concatenated.

AnalysisRun selection is manifest-first: only bars attributable to a
release-linked manifest range can enter a run. For each instrument/granularity
the selector chooses one provider/contract/dataset/schema identity, merges only
same-identity overlap, deterministically deduplicates timestamps and records
excluded alternatives. Selected manifests and bars are frozen into the immutable
input snapshot/hash for replay. Because `MarketBar` has no direct manifest
foreign key in v0.5, attribution is inferred from the exact release, provider,
contract, interval and time coverage and is disclosed as such.

One-minute bars serve short windows and earliest-reaction analysis. T+1/T+5 and
session horizons require a daily or provider-declared session-close value.
Databento `ohlcv-1d` is a UTC-day aggregate: WorldState labels it an experimental
proxy, caps quality at C and does not call it an exchange settlement/close. If
daily data or semantics are unavailable, the engine returns a data gap instead
of calculating a long-window return.

DX and VX are futures, not cash DXY or VIX. ZT and ZN are Treasury-futures price
proxies; their prices are not converted into exact cash-yield basis points.
FRED daily yields are separate observations with their own source/granularity.

## Cost gate

Before `fetch_bars`, the adapter requires an estimate and enforces both:

1. `WORLDSTATE_ALLOW_PAID_DOWNLOAD=true`;
2. estimated cost at or below
   `WORLDSTATE_DATABENTO_MAX_ESTIMATED_COST_USD`.

A valid key and dataset entitlement are also required. The current
`/v2/data/backfill/estimate` path uses a conservative local record-count fallback
unless a provider quote is explicitly supplied to the service; it is not a live
Databento bill. `POST /v2/data/backfill` persists a server-approved job consumed
by the recoverable local worker when scheduling is enabled. The worker rechecks
every gate; its existence does not grant permission to download.

Symbology, mapping, deduplication, mocked provider metadata, bar adaptation and
both cost gates have tests in the worktree. Real account permissions, continuous
mapping and billing have not been validated in this environment.

Official references:

- <https://databento.com/docs/venues-and-datasets>
- <https://databento.com/docs/standards-and-conventions/symbology>

Databento data remains subject to Databento and exchange licensing. Raw account
responses and downloaded data stay in local research storage and are not
redistributed by the repository or public API.
