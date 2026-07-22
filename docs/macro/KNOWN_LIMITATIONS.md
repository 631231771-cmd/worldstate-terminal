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

## Product limitations at Phase 0

- Macro Engine is not yet implemented.
- No provider is configured and no external data is presented as available.
- No catalog series has been validated.
- No point-in-time state, revision history, macro variant, or research workflow is
  available.

Unavailable functionality must remain explicit in API and UI responses. Missing
values must never be replaced with zero or synthetic production data.
