# Macro Engine API

Status: Phase 1 skeleton.

The service is versioned under `/v1`. Phase 1 exposes health, OpenAPI
documentation, and Prometheus metrics. Data, state, calendar, thesis, and brief
routes are intentionally unavailable until their delivery phases.

## HTTP endpoints

### `GET /v1/health`

Returns HTTP 200 with explicit component and provider states. A degraded
component is represented in the payload rather than hidden behind fabricated
data.

Important fields:

- `status`: `ok`, `degraded`, or `unavailable`;
- `database`: bounded PostgreSQL probe result;
- `providers`: per-provider status such as `not_configured` or `unsupported`;
- `default_locale` and `default_timezone`;
- `generated_at`.

Clients may send `X-Request-ID`; the service bounds it to 128 characters and
returns it in the response. Otherwise the service creates an ID.

### `GET /metrics`

Prometheus ASGI endpoint. It must not contain credentials, connection strings,
provider response bodies, or thesis content.

### `GET /docs`

FastAPI OpenAPI UI for the running service. Redoc is disabled.

## Error shape

Domain errors use:

```json
{
  "code": "stable_machine_code",
  "message": "safe operator-facing summary",
  "generated_at": "2026-07-23T00:00:00+00:00"
}
```

Unexpected driver/provider details must be collapsed to safe structured
summaries before reaching an HTTP response.

## CLI contract

The automation-safe entry point is `macro-engine`. Phase 1 implements:

- `serve`;
- `migrate`;
- `catalog validate`;
- `data-health`.

The planned commands `sync`, `backfill`, `rebuild-state`, `export-series`, and
`generate-brief` exist for discoverability but exit with code 3 and a structured
`available_in` field. They do not pretend to run.

Exit codes are 0 for success, 1 for an operational/validation error, and 3 for a
known unsupported phase.
