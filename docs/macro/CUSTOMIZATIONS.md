# Upstream customizations

This file records changes to upstream-owned files to make later synchronization
reviewable.

## Phase 0

No upstream runtime file was modified. Phase 0 added only `docs/macro/**` project
records.

## Phase 1

| Upstream file | Reason | Conflict surface | Verification |
| --- | --- | --- | --- |
| `.gitignore` | ignore Python environment, cache, and coverage output | low | `git status --short` after tests |
| `.dockerignore` | include the nested Macro Engine package README in its image context | low | Macro Engine container build |
| `Makefile` | add the requested unified macro development commands | low; append-only targets | `make help` and `make macro-test` on a POSIX runner |
| `ARCHITECTURE.md` | register the new CI workflow as required by the upstream ownership rule | low; workflow table only | `npm run docs:check` |

All other Phase 1 implementation files are new, isolated macro paths.

## Update format

For every future change, record:

- upstream file path;
- reason for the change;
- World State Terminal module that depends on it;
- likely merge-conflict surface;
- verification command.
