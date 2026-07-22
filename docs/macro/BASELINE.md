# World State Terminal upstream baseline

## Scope

This baseline was recorded before any World State Terminal implementation change.
It describes the pinned World Monitor tree and the local Windows build environment
on 2026-07-22.

## Repository identity

- Upstream: `https://github.com/koala73/worldmonitor.git`
- Pinned commit: `7fe22e47dc90ee2693d0071323561e5bbffe5c42`
- Branch: `feature/world-state-terminal`
- Remote name: `upstream`
- Initial worktree: clean
- Checkout method: a depth-one fetch of the exact pinned commit after the initial
  full clone exceeded the command time limit

## Toolchain

| Tool | Observed | Required or expected | Result |
| --- | --- | --- | --- |
| Node.js | 24.17.0 | `.nvmrc`: 24 | compatible |
| npm | 11.13.0 | lockfile-driven | compatible |
| Python | 3.13.14 | Macro Engine: 3.12 | mismatch; Phase 1 must use an isolated 3.12 runtime |
| uv | unavailable | required for Macro Engine | install in Phase 1 |
| Rust/Cargo | unavailable | Tauri stable toolchain | desktop build not runnable locally |
| Go | unavailable | proto plugin installation | full proto generation not runnable locally |
| Buf | local npm package 1.66.1 | Buf CLI | lint can run; sebuf plugins remain unavailable |
| Playwright Chromium | unavailable | required for E2E | download timed out after 304 seconds |

## Dependency installation

Command: `npm ci --no-audit --no-fund`

Result: passed. The root installed 1669 packages and the blog postinstall installed
294 packages. The lockfile did not change. npm reported two high-severity findings;
no automatic remediation was applied and `npm audit fix --force` was not run.

The first install attempt hit the command time limit. A second deterministic run
completed successfully after the interrupted child process released its files.

## Baseline commands

| Command | Result | Notes |
| --- | --- | --- |
| `npm run typecheck` | pass | `tsc --noEmit` |
| `npm run typecheck:all` | pass | frontend, API, and Convex string-call audit |
| `npm run lint` | pass | 25 upstream warnings and 3 infos; safe HTML guard passed |
| `npm run test:sidecar` | pass | 250 tests, 0 failures |
| `npm run test:data` | fail | fixed upstream tree fails before macro changes; see below |
| `npm run build:finance` | pass | 2359 modules transformed; PWA generated |
| `npm run build:full` | fail | blog built 75 pages, then Windows could not execute the POSIX `rm` command |
| `npx cross-env-shell VITE_VARIANT=full "tsc && vite build"` | pass | equivalent core full TypeScript/Vite production build |
| `npx buf lint proto` | fail | existing unused imports and inconsistent `go_package` declarations |
| `make generate` | unavailable | `make`, Go, and pinned sebuf plugins are absent |
| finance variant E2E smoke | unavailable | upstream webServer command is POSIX-only on Windows; cross-platform retry reached a missing browser, whose download timed out |

## Existing test failures

`npm run test:data` was run twice before implementation and returned exit code 1
both times. The failures are independent of World State Terminal because the
worktree had no macro changes. Representative categories are:

- generated artifact drift: agent-skills index and multiple OpenAPI injectors;
- Windows path construction producing paths such as `F:\F:\Code\...`;
- tests requiring a prior `dist/dashboard.html` build;
- source-contract drift for panel layout, premium fetch, product pricing, and
  Docker services;
- locale size and marker animation guardrails;
- protocol and registry publication artifacts that are out of sync.

The baseline build commands temporarily refreshed generated artifacts. Their
content hashes were restored to the pinned commit before project changes began.
No unrelated upstream failure is fixed as part of Phase 0 or Phase 1.

## Reproduction notes

Use Node 24 and run commands serially. The upstream agent guide warns that heavy
checks can exhaust memory when run concurrently. On Windows, use the equivalent
cross-platform full build command above until the upstream `build:blog` script is
made platform-neutral. A Linux CI runner remains the canonical environment for
proto generation and E2E.
