# Architecture decision records

## ADR-0001: Pin the upstream commit

- Status: accepted
- Date: 2026-07-22

### Decision

Build on World Monitor commit `7fe22e47dc90ee2693d0071323561e5bbffe5c42`,
rename the source remote to `upstream`, and develop on
`feature/world-state-terminal`.

### Consequences

Builds are reproducible and upstream drift is explicit. Security or compatibility
updates require a reviewed pin change rather than an implicit dependency move.

## ADR-0002: Add an isolated Macro Engine

- Status: accepted
- Date: 2026-07-22

### Decision

Keep point-in-time macro persistence and deterministic state computation in
`services/macro-engine`, behind the existing World Monitor gateway.

### Consequences

The browser remains secret-free and upstream merge conflicts are constrained.
Local deployment has an additional Python/PostgreSQL runtime.

## ADR-0003: PostgreSQL and Alembic are the production persistence path

- Status: accepted
- Date: 2026-07-22

### Decision

Use PostgreSQL 16 through SQLAlchemy 2 and asyncpg. Apply all production schema
changes with Alembic; never use `create_all` as a migration mechanism.

### Consequences

As-of indexing, JSON metadata, advisory locks, and durable migrations have one
supported implementation. Unit tests may use fakes but cannot redefine database
semantics.

## ADR-0004: Availability semantics are first-class data

- Status: accepted
- Date: 2026-07-22

### Decision

Persist `period_start`, `period_end`, `available_at`, `vintage_date`,
`realtime_start`, `realtime_end`, and `fetched_at` separately. Strict queries
exclude records whose availability cannot be trusted.

### Consequences

Historical results can be reproducible and free of known look-ahead leakage.
Coverage is intentionally lower when providers lack release history.

## ADR-0005: Provider absence is a valid operating state

- Status: accepted
- Date: 2026-07-22

### Decision

Start the service without external credentials. Represent missing configuration,
upstream failure, stale data, and unsupported capability explicitly.

### Consequences

Development and self-hosting do not depend on every vendor. Tests use fixtures;
fixtures are never exposed as real production observations.

## ADR-0006: Phase 1 does not install OpenBB at runtime by default

- Status: accepted
- Date: 2026-07-22

### Decision

Pin `openbb==4.7.2` in an optional dependency group during the skeleton phase.
Core health, migration, catalog, and provider-contract development must run without
downloading the large optional provider stack.

### Consequences

The service remains fast to bootstrap and CI can exercise its contract without
provider credentials. Provider-specific tests must install the `openbb` extra.
