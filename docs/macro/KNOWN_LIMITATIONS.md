# Known limitations

## Baseline limitations

- The fixed upstream commit has existing `test:data` and proto lint failures.
- The upstream `build:full` wrapper is not Windows-compatible because its blog
  copy step uses POSIX file commands. The core full TypeScript/Vite build passes.
- Rust/Cargo and Go/sebuf generation plugins are unavailable in the audited local
  environment.
- Playwright Chromium could not be downloaded within the available network window,
  so the critical browser smoke remains unavailable locally.
- npm reports two high-severity dependency findings in the existing lockfile.
  No force remediation was attempted.

## Product limitations after Phase 1

- Macro Engine provides a service, schema, protocol, catalog, health, and CLI
  skeleton; provider ingestion and scoring intentionally begin in Phase 2.
- No provider adapter is active and no external observation is presented as
  available.
- Eight initial U.S. catalog entries pass structural validation, but live source
  metadata validation requires the Phase 2 FRED/ALFRED adapter and credentials.
- No point-in-time state, revision history, macro variant, or research workflow is
  available.
- The local verification machine has no Docker CLI. Compose and Dockerfile
  invariants were checked statically, while the Linux CI workflow owns the live
  PostgreSQL migration and image build.
- The FastAPI test client emits an upstream Starlette deprecation warning about
  the current `httpx` integration. Tests pass; a coordinated dependency update is
  deferred rather than overriding the lock without evidence.
- OpenBB 4.7.2 is locked as an optional extra but is not installed in the default
  service or container environment.

Unavailable functionality must remain explicit in API and UI responses. Missing
values must never be replaced with zero or synthetic production data.
