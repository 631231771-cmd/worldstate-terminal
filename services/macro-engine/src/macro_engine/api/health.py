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
    except Exception as exc:
        return ComponentHealth(
            status=ServiceStatus.UNAVAILABLE,
            message=f"database probe failed: {type(exc).__name__}",
        )


def provider_summaries(settings: Settings) -> list[ProviderHealthSummary]:
    """Report provider configuration without disclosing credentials."""

    fred_status = ProviderStatus.OK if settings.fred_api_key else ProviderStatus.NOT_CONFIGURED
    fred_message = (
        "configured; live availability is verified during synchronization"
        if settings.fred_api_key
        else "FRED_API_KEY is not configured; explicit Demo mode is available"
    )
    return [
        ProviderHealthSummary(key="fred_alfred", status=fred_status, message=fred_message),
        ProviderHealthSummary(
            key="public_intelligence",
            status=ProviderStatus.OK,
            message="keyless RSS and public daily market evidence enabled",
        ),
        ProviderHealthSummary(
            key="ai_tutor",
            status=(
                ProviderStatus.OK
                if settings.resolved_ai_provider != "none"
                else ProviderStatus.NOT_CONFIGURED
            ),
            message=(
                f"{settings.resolved_ai_provider} configured"
                if settings.resolved_ai_provider != "none"
                else "AI is optional; deterministic evidence tutor remains available"
            ),
        ),
        ProviderHealthSummary(
            key="openbb",
            status=ProviderStatus.UNSUPPORTED,
            message="optional adapter is not enabled",
        ),
        ProviderHealthSummary(
            key="world_bank",
            status=ProviderStatus.UNSUPPORTED,
            message="adapter is not enabled",
        ),
        ProviderHealthSummary(
            key="bis",
            status=ProviderStatus.UNSUPPORTED,
            message="adapter is not enabled",
        ),
    ]


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service, database, and provider readiness without leaking secrets."""

    settings: Settings = request.app.state.settings
    database = await probe_database(request, settings.health_timeout_seconds)
    providers = provider_summaries(settings)
    warnings = []
    if not settings.fred_api_key:
        warnings.append("FRED is not configured; synchronization uses explicit Demo fixtures")
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
        methodology_version="wst-state-v1",
        warnings=warnings,
    )
