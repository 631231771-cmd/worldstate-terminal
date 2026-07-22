# Third-party inventory

## Policy

This inventory is provisional until dependency locking in Phase 1. Exact package
metadata and license texts must be captured from the resolved distributions before
a release candidate. Dataset terms are reviewed separately from software package
licenses.

## Planned Macro Engine dependencies

| Package or service | Pinned or planned version | Purpose | Review status |
| --- | --- | --- | --- |
| OpenBB | 4.7.2 | provider and data access layer | license and provider-terms review required |
| FastAPI / Uvicorn | lockfile resolution | HTTP service | pending locked metadata review |
| Pydantic / pydantic-settings | major version 2 | validation and settings | pending locked metadata review |
| SQLAlchemy / asyncpg / Alembic | current compatible lock | PostgreSQL and migrations | pending locked metadata review |
| httpx / tenacity | current compatible lock | provider HTTP, timeout, retry | pending locked metadata review |
| Polars / NumPy | current compatible lock | deterministic transforms | pending locked metadata review |
| APScheduler | current compatible lock | local scheduling | pending locked metadata review |
| PyYAML / structlog / prometheus-client | current compatible lock | catalog, logs, metrics | pending locked metadata review |
| pytest / pytest-asyncio / respx / hypothesis / coverage | current compatible lock | tests | pending locked metadata review |
| Ruff / mypy | current compatible lock | quality gates | pending locked metadata review |

## Planned data providers

FRED/ALFRED, World Bank, BIS, DBnomics, IMF, OECD, EIA, and OpenBB-backed
providers each require source-specific terms, attribution, credential, caching,
and redistribution review. Provider availability never implies permission to
redistribute its data.
