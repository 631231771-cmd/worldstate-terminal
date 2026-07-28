# Macro Engine security

Status: Phase 1 boundary definition.

## Secrets

Secrets are read only from environment-backed settings. The service must never
commit or return provider keys, AI keys, database credentials, write tokens, or
authenticated provider URLs.

Structured logging recursively redacts sensitive key names, bearer tokens, and
URL user information. Database probe errors return only the exception class.

## Writes

Write capability is fail-closed. It is available only when both conditions hold:

1. `MACRO_ENABLE_WRITES=true`;
2. `MACRO_WRITE_TOKEN` is configured.

Phase 1 exposes no write routes. Future gateway and service routes must enforce
the token server-side and must not place it in a browser bundle.

The Phase 10 event research journal is not a Macro Engine write route. It uses
origin-scoped browser storage and can export a local Markdown file. The native
desktop profile is stored under ignored `.runtime/desktop-profile`; journal
text, revision history, and exported notes are never added to API requests,
logs, Git, or AI prompts automatically.

## Network boundary

- Macro Engine binds to loopback by default.
- Compose publishes its port on `127.0.0.1` by default.
- Public deployments require an operator-managed TLS/authentication boundary.
- Provider adapters must use allowlisted HTTPS origins, bounded timeouts, retry
  budgets, concurrency limits, response validation, and source attribution.

## Data integrity

- Production schema changes use reviewed Alembic migrations.
- Missing data remains missing; zero substitution and synthetic production
  observations are forbidden.
- Strict point-in-time mode excludes unknown availability until an explicit
  provider policy exists.
- Catalog validation rejects duplicate canonical keys and duplicate
  provider/native identifiers.

## Supply chain and licensing

Python registry artifacts are hash-locked by `uv.lock`. OpenBB is isolated as an
optional extra, fixed at 4.7.2, and excluded from the default container. The
upstream application remains AGPL-3.0-only. Macro Engine licensing and provider
redistribution terms remain pending legal review; see `LICENSE_REVIEW.md` and
`THIRD_PARTY.md`.

## Deferred controls

Phase 2 adds provider-specific rate limits, response schemas, idempotency, and
look-ahead tests. Gateway authentication, CORS, and public rate limits arrive
with the Phase 3 integration. Backup/restore drills and a complete dependency
advisory review are Phase 7 gates.
