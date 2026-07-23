# Issues and risk register

| ID | Risk or issue | Impact | Phase | Mitigation |
| --- | --- | --- | --- | --- |
| WST-001 | Upstream `test:data` is red at the pinned commit | obscures regressions | 0-1 | keep macro tests isolated and retain baseline failure categories |
| WST-002 | Full build wrapper uses POSIX file commands on Windows | wrapper fails locally | 0 | verify core full build; rely on Linux CI for canonical wrapper |
| WST-003 | Proto lint and generated artifacts already drift | future macro proto gate may be noisy | 3 | add macro contracts only after a clean, pinned sebuf environment is available |
| WST-004 | System Python is 3.13, not 3.12 | unsupported runtime mismatch | 1 | resolved: `uv` manages Python 3.12.13; CI pins 3.12 |
| WST-005 | Rust, Go, and sebuf plugins are absent | desktop/proto checks unavailable | 0-3 | keep Phase 1 independent; run canonical checks in CI |
| WST-006 | Playwright browser download timed out | browser smoke unavailable locally | 0 | CI installs browser; retry locally when network permits |
| WST-007 | Existing npm audit has two high findings | supply-chain exposure | 0-7 | review advisories without force upgrades; update only through scoped changes |
| WST-008 | AGPL and data-provider terms affect distribution | legal exposure | all | preserve notices, keep license pending, complete release legal review |
| WST-009 | Availability timestamps vary by provider | look-ahead bias | 2 | persist method/precision; strict mode excludes unknown availability |
| WST-010 | Optional provider outage or missing keys | partial data | all | explicit not-configured/unavailable/stale states and fixtures for tests |
| WST-011 | OpenBB has a large dependency surface | slow CI and deployment | 1-2 | pin 4.7.2 as an optional extra and use official adapters where needed |
| WST-012 | State methodology can be mistaken for advice | product and compliance risk | 2-7 | deterministic evidence, semantic labels, limitations, no trade instructions |
| WST-013 | Docker CLI is unavailable on the local verifier | live Compose/PostgreSQL/image checks cannot run locally | 1 | static invariants pass; Linux CI runs migrations and the image build |
