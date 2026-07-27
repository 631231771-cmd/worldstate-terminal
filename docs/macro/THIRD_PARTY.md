# Third-party inventory

## Policy

The Python graph is locked by `services/macro-engine/uv.lock`. The table below
records the direct dependency versions installed by the Phase 1 core/development
environment and the license metadata exposed by those distributions. Exact
license texts and all transitive packages still require a release-candidate
notice bundle. Dataset terms are reviewed separately from software licenses.

## Locked Macro Engine dependencies

| Package or service | Locked version | Purpose | Distribution metadata |
| --- | --- | --- | --- |
| OpenBB | 4.7.2, optional extra | provider/data access | not installed by default; license and provider terms pending |
| FastAPI / Uvicorn | 0.136.3 / 0.40.0 | HTTP service | MIT / BSD-3-Clause |
| Pydantic / pydantic-settings | 2.13.4 / 2.14.2 | validation and settings | MIT / MIT |
| SQLAlchemy / asyncpg / Alembic | 2.0.51 / 0.31.0 / 1.18.5 | PostgreSQL and migrations | MIT / Apache-2.0 / MIT |
| httpx / tenacity | 0.28.1 / 9.1.4 | provider HTTP, timeout, retry | BSD-3-Clause / Apache-2.0 |
| Polars / NumPy | 1.43.0 / 2.5.1 | deterministic transforms | package metadata captured; notice review pending |
| APScheduler | 3.11.3 | local scheduling | MIT |
| PyYAML / structlog | 6.0.3 / 25.5.0 | catalog and logs | MIT / MIT OR Apache-2.0 |
| prometheus-client | 0.25.0 | metrics | Apache-2.0 AND BSD-2-Clause |
| pytest / pytest-asyncio | 8.4.2 / 0.26.0 | tests | MIT / Apache-2.0 |
| respx / Hypothesis / coverage | 0.23.1 / 6.160.0 / 7.15.2 | tests | BSD-3-Clause / MPL-2.0 / Apache-2.0 |
| Ruff / mypy | 0.15.22 / 1.20.2 | quality gates | MIT / MIT |

## Referenced integration projects

| Project | Reviewed revision | Use | License |
| --- | --- | --- | --- |
| [ClawFeed](https://github.com/lvy010/clawfeed) | `38b43f0c3d5c781acbc3173a3a4a47f480cb18a5` | optional public digest adapter and editorial-model reference | MIT |
| [WebMCP](https://github.com/lvy010/webmcp) | `971aa24aea2afd865ca8607ba79a486fc7429360` | browser page-tool proposal and interface reference | W3C Software and Document License |
| [Agent Reach](https://github.com/Panniantong/agent-reach) | installed `v1.5.0`; upstream update checked 2026-07-27 | optional local read-only X transport | MIT |

No source file from these projects is vendored. World State Terminal's
adapters and page-tool implementation are original code behind optional,
feature-detected boundaries. Agent Reach and its `twitter` command remain
separately installed user-level tools; the repository stores no X credential.

`uv.lock` includes hashes for registry artifacts. `python -m uv sync --group
dev` installed 56 packages without the OpenBB extra; `python -m uv lock
--check` confirmed the lock remained current.

## Planned data providers

FRED/ALFRED, World Bank, BIS, DBnomics, IMF, OECD, EIA, and OpenBB-backed
providers each require source-specific terms, attribution, credential, caching,
and redistribution review. Provider availability never implies permission to
redistribute its data.
