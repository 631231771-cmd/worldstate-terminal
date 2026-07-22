"""Health and readiness endpoints."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import text

from macro_engine import __version__
from macro_engine.config import Settings
from macro_engine.domain.enums import ProviderStatus, ServiceStatus
from macro_engine.domain.schemas import (
    ComponentHealth,
    HealthResponse,
    ProviderHealthSummary,
)

router = APIRouter(prefix="/v1", tags=["health"])


async def probe_database(request: Request, timeout_seconds: float) -> ComponentHealth:
    """Probe PostgreSQL with a bounded query and a structured degraded result."""

    try:
        async with asyncio.timeout(timeout_seconds):
            async with request.app.state.database_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return ComponentHealth(status=ServiceStatus.OK)
    except Exception as exc:  # noqa: BLE001 - health must collapse driver failures
        return ComponentHealth(
            status=ServiceStatus.UNAVAILABLE,
            message=f"database probe failed: {type(exc).__name__}",
        )


def provider_summaries(settings: Settings) -> list[ProviderHealthSummary]:
    """Report configuration state without contacting providers in Phase 1."""

    fred_status = ProviderStatus.DEGRADED if settings.fred_api_key else ProviderStatus.NOT_CONFIGURED
    fred_message = (
        "adapter implementation is scheduled for Phase 2"
        if settings.fred_api_key
        else "FRED_API_KEY is not configured"
    )
    return [
        ProviderHealthSummary(key="fred_alfred", status=fred_status, message=fred_message),
        ProviderHealthSummary(
            key="openbb",
            status=ProviderStatus.UNSUPPORTED,
            message="optional adapter is not enabled in Phase 1",
        ),
        ProviderHealthSummary(
            key="world_bank",
            status=ProviderStatus.UNSUPPORTED,
            message="adapter implementation is scheduled for Phase 4",
        ),
        ProviderHealthSummary(
            key="bis",
            status=ProviderStatus.UNSUPPORTED,
            message="adapter implementation is scheduled for Phase 4",
        ),
    ]


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service, database, and provider readiness without leaking secrets."""

    settings: Settings = request.app.state.settings
    database = await probe_database(request, settings.health_timeout_seconds)
    providers = provider_summaries(settings)
    warnings = [
        "state methodology is unavailable until Phase 2",
        "provider adapters are unavailable or not configured",
    ]
    status = ServiceStatus.OK if database.status is ServiceStatus.OK else ServiceStatus.DEGRADED
    return HealthResponse(
        version=__version__,
        status=status,
        generated_at=datetime.now(UTC),
        database=database,
        providers=providers,
        writes_enabled=settings.writes_available,
        default_locale=settings.default_locale,
        default_timezone=settings.default_timezone,
        warnings=warnings,
    )

