# Macro Engine API

Status: Phase 3 world-explanation MVP.

The browser talks only to the Macro Engine `/v1` API. Provider credentials never
cross this boundary. The frontend client is centralized in
`src/services/macro-client.ts`; its URL comes from `VITE_MACRO_ENGINE_URL`, an
explicit local override, or `http://127.0.0.1:8000`.

## Read endpoints

### `GET /v1/health`

Returns database reachability, provider configuration, locale, timezone, service
version, methodology version, and safe warnings. Database errors are collapsed
without returning connection strings.

### `GET /v1/snapshot`

Returns the complete terminal home payload:

- explicit `LIVE`, `STALE`, `DEMO`, or `EMPTY` mode;
- eight state scores with label, confidence, trend, drivers, missing series,
  staleness, experimental status, and as-of date;
- top release, revision, extreme-state, and stale-data changes;
- growth/inflation regime point and six-point trajectory;
- release calendar and system health.

A state with insufficient evidence has a `null` score and
`insufficient_data` label. It is never replaced with zero.

### `GET /v1/world/briefing`

Returns the news-first terminal payload:

- five ranked high-impact world events from free public feeds;
- original headline, publisher, link, publication time, and importance;
- a Chinese learning title, why-it-matters explanation, causal chain, affected
  assets, and confidence for each event;
- daily prices and percentage moves for gold, S&P 500, Nasdaq, the U.S. dollar
  index, U.S. 10-year yield, WTI, Bitcoin, Shanghai Composite, Hang Seng,
  Nikkei 225, and KOSPI;
- per-market cross-asset explanation, evidence, confidence, and explicit
  `order_flow_known: false` where institutional flow is not observable;
- one daily lesson, upcoming macro releases, compact macro state context,
  source inventory, AI status, and honest limitations.

`evidence_mode` is `LIVE`, `PARTIAL`, or `OFFLINE` and is separate from the
FRED observation mode. Responses are cached for five minutes unless
`?fresh=true` is supplied.

### `GET /v1/world/ai-status`

Returns the resolved AI provider, model, availability, and deterministic
fallback name. It never returns credentials.

### `GET /v1/series`

Lists the local catalog with canonical key, provider ID, frequency, unit,
default transform, source URL, and live/demo source mode.

### `GET /v1/series/{canonical_key}`

Returns the point-in-time latest vintage for each observation period. Query
parameters:

- `transform`: `level`, `difference`, `percent_change`, `yoy`, `qoq`,
  `annualized_3m`, `annualized_6m`, `moving_average`,
  `rolling_percentile`, or `rolling_zscore`;
- `as_of`: optional ISO timestamp. Observations unavailable at that time are
  excluded before transforms run.

The response includes raw/transformed values, rolling percentile, vintage date,
source metadata, and revision count.

### `GET /metrics` and `GET /docs`

Prometheus ASGI endpoint and FastAPI OpenAPI UI.

## CPI Event Lab endpoints

### `GET /v1/events/lab/status`

Returns the CPI vertical-slice state, methodology version, demonstration event
ID, event/bar/window/analysis counts, supported indicators and instruments,
and explicit fixture/proxy warnings.

### `GET /v1/events?event_type=US_CPI`

Lists CPI releases with all four indicator values, latest pre-release consensus
snapshot, previous and revised-previous values, surprise, composite
classification, contamination state, confidence, and analysis status.

### `GET /v1/events/{event_id}`

Returns one complete CPI research packet:

- four-indicator EventBundle and point-in-time consensus history;
- normalized cross-asset minute timeline;
- T-60/T-15 and T+1/T+5/T+15/T+30/T+60/T+4h window metrics;
- explicitly incomplete U.S. close, next-close, and five-day windows when the
  imported data does not cover those sessions;
- first volatility-adjusted, consecutively confirmed reaction observable at
  the source granularity;
- spike-fade, dip-recovery, and direction-reversal flags;
- confirmed facts, primary rules, competing explanations, contamination
  constraints, confidence, and data gaps;
- fixed-filter historical statistics or a sample-safe case-study downgrade;
- source, acquisition, manual/verified/fixture/proxy, granularity, latency,
  missing-reason, and quality-grade metadata.

### Controlled write endpoints

- `POST /v1/events/cpi` creates or updates a complete four-indicator CPI bundle.
- `POST /v1/events/{event_id}/consensus` appends a pre-release consensus
  snapshot. A snapshot at or after release time is rejected.
- `POST /v1/events/{event_id}/market-bars/import` imports normalized CSV bars
  for GC, SI, DXY, ES, NQ, ZT, or ZN through the provider boundary.
- `POST /v1/events/{event_id}/analyze` deterministically reruns the analysis.

The CSV fields are `timestamp`, `instrument_key`, `open`, `high`, `low`,
`close`, with optional `volume`, `interval_seconds`, `source_symbol`, and
`contract_code`. Timestamps must include a timezone.

Loopback desktop requests from the configured frontend origins may write
without placing a secret in browser code. Non-local writes require
`MACRO_ENABLE_WRITES=true` and a matching bearer or `X-Write-Token`.

## Tutor endpoint

### `POST /v1/world/ask`

Request:

```json
{
  "question": "为什么黄金会在美联储讲话后波动？",
  "mode": "deep",
  "history": [
    {
      "role": "user",
      "content": "先解释实际利率"
    }
  ]
}
```

`mode` is `beginner`, `deep`, or `socratic`. The server constructs the evidence
pack; the browser cannot inject its own market facts. Responses include answer,
provider, model, grounding flag, source links, fallback warning, and
educational disclaimer.

OpenAI uses the Responses API. Ollama uses its local chat API. Generic
OpenAI-compatible providers use `chat/completions`. With no AI provider, the
same route returns a deterministic evidence-based teaching answer.

## CLI contract

Implemented commands:

- `serve`;
- `migrate`;
- `catalog validate`;
- `sync --all`, `sync --series <canonical-key-or-FRED-id>`, and
  `sync --recent-days <days>`;
- `backfill --from <date>`;
- `sync-history [--series ...]`;
- `rebuild-state --from <date>`;
- `data-health`.

Invalid catalog series and individual provider failures are warnings. They do
not terminate synchronization or prevent the application from starting.
`export-series` and `generate-brief` remain future surfaces.

Exit codes are 0 for success, 1 for an operational/validation error, 2 for CLI
usage, and 3 for a declared unsupported command.
