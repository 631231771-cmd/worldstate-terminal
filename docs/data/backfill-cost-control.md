# Backfill and cost control

The supported v0.5 request scope is intentionally bounded to US CPI, US NFP and
FOMC, and GC, SI, CL, ES, NQ, ZT, ZN, DX and VX. The default start date is
`WORLDSTATE_DATA_START_DATE=2015-01-01`.

## What exists now

`GET /v2/data/backfill/estimate` returns event/asset counts, dataset/schema
groups, intraday minute range, estimated records/bytes/cost, existing manifest
coverage, configured budget and a decision/reason. Event count is frequency-based
until official calendars are persisted; cost is a local record-count fallback,
not a live Provider invoice quote.

`POST /v2/data/backfill` recomputes the estimate server-side and persists an
idempotent estimated/pending/rejected job. A recoverable local worker consumes
approved pending jobs while the scheduler is enabled, rechecks the cost/access
gates, records stage progress and retains partial results. Status and
cancellation endpoints are implemented.

## Paid execution policy

An observed Databento execution may proceed only when all of these are
true:

- a Databento credential is configured and valid;
- the account is entitled to the requested dataset/schema;
- `WORLDSTATE_ALLOW_PAID_DOWNLOAD=true` is explicitly set;
- a current estimate is at or below
  `WORLDSTATE_DATABENTO_MAX_ESTIMATED_COST_USD`;
- the event, asset and date scope passes validation;
- the worker reuses completed manifests/idempotency keys instead of blindly
  redownloading data.

The Provider adapter already enforces the explicit opt-in plus budget ceiling
before bar retrieval. The API boundary additionally blocks an unconfigured key.
Neither a UI click nor a caller-supplied estimate ID bypasses the server-side
calculation.

## Still required for real backfill

1. Re-run the wired official calendar/release sync where upstream access is
   available (the current network receives HTTP 403 from BLS schedule HTML).
2. Obtain/validate legally usable TE PIT consensus and Databento entitlements.
3. Validate provider metadata cost quotes and actual-cost capture against a real
   entitled account.
4. Reconcile/grade every completed slice before using it in an observed analysis.

The no-key v0.5 validation environment cannot demonstrate real historical
backfill and makes no such claim.
