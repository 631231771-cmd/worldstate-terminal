# Macro Engine API

Status: Phase 2 local-first MVP.

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
