# Data reconciliation

Reconciliation preserves both sides of a disagreement; it never “fixes” a
difference by deleting provenance or overwriting the authoritative value.

## Implemented service primitives

For macro fields, `reconcile_values` compares official and secondary values with
an explicit unit/tolerance, retains both artifact references and stores matched,
mismatch or missing status plus the numeric difference when meaningful. Official
BLS/Federal Reserve inputs remain authoritative for analysis.

For market manifests, `record_market_reconciliation` records a named set of
integrity checks and failed checks without mutating the source bars. Persisted
records are idempotent and can later be resolved with an action/note while
keeping the original evidence.

These service paths and non-destructive/idempotent behavior are connected to the
TE/market ingestion services. CLI/API `reconcile-data` and the overnight job
rerun comparisons from persisted records; the overnight pass does not perform a
new TE request.

## Intended macro checks

Official BLS/Federal Reserve values are compared with mapped Trading Economics
snapshots across release time, actual, previous, revision, unit and reference
period. Both source artifacts remain linked. A secondary mismatch lowers TE
quality; it never replaces the official value.

## Intended market checks

A completed market slice should be checked for contract validity at T0,
timestamp/timezone normalization, session membership, OHLC consistency,
duplicates, gaps, roll crossings and expected-session coverage. A contract/roll
change requires an explicit manifest rather than silent stitching.

Repeated/overnight market validation merges with ingestion-time checks so a
count-only pass cannot erase contract, OHLC, gap, timezone, roll or session
evidence. Fixture reconciliation cannot satisfy observed coverage; an empty
observed view remains honest when no observed manifests exist.
