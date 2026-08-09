"""Runtime construction and persistence helpers for v0.5 data providers."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    json_safe,
    record_provider_run,
    record_source_artifact,
)
from worldstate.config import Settings
from worldstate.data_quality import DataQuality
from worldstate.db.models import DataQualityRecord, SourceArtifact
from worldstate.macro_core.models import ProviderHealth
from worldstate.provider_kit import (
    BlsOfficialProvider,
    DatabentoMarketProvider,
    FederalReserveFomcProvider,
    FredAlfredProvider,
    OfficialPublicCsvProvider,
    ProviderCapabilities,
    ProviderRetryPolicy,
    ProviderTerms,
    PublicSeriesSpec,
    TradingEconomicsConsensusProvider,
)
from worldstate.provider_kit import (
    SourceArtifact as ProviderSourceArtifact,
)

_QUALITY_NAMESPACE = uuid.UUID("d4858b68-a476-4b52-bfa6-9d819956332f")


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


@dataclass(frozen=True, slots=True)
class ProviderClients:
    bls: BlsOfficialProvider
    federal_reserve: FederalReserveFomcProvider
    fred: FredAlfredProvider
    trading_economics: TradingEconomicsConsensusProvider
    databento: DatabentoMarketProvider
    ecb: OfficialPublicCsvProvider
    boj: OfficialPublicCsvProvider
    boe: OfficialPublicCsvProvider
    china: OfficialPublicCsvProvider


class _HealthProvider(Protocol):
    key: str

    def get_capabilities(self) -> ProviderCapabilities: ...

    async def healthcheck(self) -> ProviderHealth: ...


def build_provider_clients(
    settings: Settings,
    *,
    trading_economics_monthly_requests_used: int = 0,
) -> ProviderClients:
    retry_policy = ProviderRetryPolicy(max_attempts=settings.provider_retry_attempts)
    return ProviderClients(
        bls=BlsOfficialProvider(
            _secret(settings.bls_api_key),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        federal_reserve=FederalReserveFomcProvider(
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        fred=FredAlfredProvider(
            _secret(settings.fred_api_key),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        trading_economics=TradingEconomicsConsensusProvider(
            _secret(settings.trading_economics_api_key),
            pit_entitled=settings.trading_economics_pit_entitled,
            monthly_quota=settings.trading_economics_monthly_quota,
            monthly_requests_used=trading_economics_monthly_requests_used,
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        databento=DatabentoMarketProvider(
            _secret(settings.databento_api_key),
            max_estimated_cost_usd=settings.databento_max_estimated_cost_usd,
            allow_paid_download=settings.allow_paid_download,
            timeout_seconds=max(settings.provider_timeout_seconds, 60),
            retry_policy=retry_policy,
        ),
        ecb=OfficialPublicCsvProvider(
            key="ecb_data_portal",
            name="European Central Bank Data Portal",
            base_url=settings.ecb_api_url,
            terms=ProviderTerms(
                license_name="ECB Data Portal terms",
                terms_url="https://data.ecb.europa.eu/help/terms-of-use",
                redistribution_allowed=True,
            ),
            series=(
                PublicSeriesSpec(
                    native_id="EXR.D.USD.EUR.SP00.A",
                    canonical_key="EA.EXTERNAL.EURUSD",
                    title="US dollar per euro reference rate",
                    entity="EA19",
                    frequency="daily",
                    unit="USD_per_EUR",
                    source_url="https://data.ecb.europa.eu/data/datasets/EXR/EXR.D.USD.EUR.SP00.A",
                ),
                PublicSeriesSpec(
                    native_id="ICP.M.U2.N.000000.4.ANR",
                    canonical_key="EA.INFLATION.HICP",
                    title="Euro Area HICP annual rate",
                    entity="EA19",
                    frequency="monthly",
                    unit="percent",
                    source_url="https://data.ecb.europa.eu/data/datasets/ICP/ICP.M.U2.N.000000.4.ANR",
                ),
                PublicSeriesSpec(
                    native_id="FM.D.U2.EUR.4F.MM",
                    canonical_key="EA.POLICY.ECB_DEPOSIT_RATE",
                    title="ECB deposit facility rate",
                    entity="EA19",
                    frequency="daily",
                    unit="percent",
                    source_url="https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.MM",
                ),
            ),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        boe=OfficialPublicCsvProvider(
            key="bank_of_england_iadb",
            name="Bank of England IADB",
            base_url=settings.boe_api_url,
            terms=ProviderTerms(
                license_name="Bank of England IADB terms",
                terms_url="https://www.bankofengland.co.uk/boeapps/database/iadb-notes.asp",
                redistribution_allowed=True,
            ),
            series=(
                PublicSeriesSpec(
                    native_id="IUDBEDR",
                    canonical_key="GBR.POLICY.BANK_RATE",
                    title="Bank Rate",
                    entity="GBR",
                    frequency="daily",
                    unit="percent",
                    source_url="https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
                    value_column="IUDBEDR",
                    date_column="DATE",
                    endpoint_kind="boe",
                ),
            ),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        boj=OfficialPublicCsvProvider(
            key="boj_public",
            name="Bank of Japan public export",
            base_url=settings.boj_api_url or "",
            terms=ProviderTerms(
                license_name="Bank of Japan public data terms",
                terms_url="https://www.stat-search.boj.or.jp/",
                redistribution_allowed=True,
            ),
            series=(),
            enabled=bool(settings.boj_api_url),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
        china=OfficialPublicCsvProvider(
            key="china_official_public",
            name="China official macro export",
            base_url=settings.china_api_url or "",
            terms=ProviderTerms(
                license_name="China official statistics publication terms",
                terms_url="https://www.stats.gov.cn/",
                redistribution_allowed=False,
            ),
            series=(),
            enabled=bool(settings.china_api_url),
            timeout_seconds=settings.provider_timeout_seconds,
            retry_policy=retry_policy,
        ),
    )


async def persist_provider_artifact(
    engine: AsyncEngine,
    artifact: ProviderSourceArtifact,
    *,
    provider_run_id: uuid.UUID | None,
    data_mode: Literal["observed", "fixture"] = "observed",
    title: str | None = None,
) -> SourceArtifact:
    return await record_source_artifact(
        engine,
        source_key=f"{artifact.provider_key}:{artifact.content_hash}",
        provider_key=artifact.provider_key,
        artifact_type=artifact.content_type,
        title=title or str(artifact.metadata.get("title") or artifact.source_url),
        source_url=artifact.source_url,
        content=artifact.content,
        content_type=artifact.content_type,
        retrieved_at=artifact.retrieved_at,
        published_at=artifact.published_at,
        license_name=artifact.license_name,
        citation_text=f"{artifact.provider_key}: {artifact.source_url}",
        data_mode=data_mode,
        provider_run_id=provider_run_id,
        metadata={
            **artifact.metadata,
            "terms_url": artifact.terms_url,
            "raw_payload_local_only": True,
        },
    )


async def persist_quality_record(
    engine: AsyncEngine,
    quality: DataQuality,
    *,
    subject_type: str,
    subject_id: str,
    identity: str,
) -> DataQualityRecord:
    data_mode = "fixture" if quality.is_fixture else "observed"
    record_id = uuid.uuid5(_QUALITY_NAMESPACE, f"{data_mode}:{identity}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        existing = await session.get(DataQualityRecord, record_id)
        if existing is not None:
            return existing
        row = DataQualityRecord(
            id=record_id,
            subject_type=subject_type,
            subject_id=subject_id,
            source_name=quality.source_name,
            source_url=quality.source_url,
            source_type=quality.source_type,
            acquired_at=quality.acquired_at,
            is_manual=quality.is_manual,
            is_verified=quality.is_verified,
            is_fixture=quality.is_fixture,
            is_proxy=quality.is_proxy,
            latency_seconds=quality.latency_seconds,
            granularity_seconds=quality.granularity_seconds,
            missing_reason=quality.missing_reason,
            quality_grade=quality.quality_grade.value,
            verification_notes=quality.verification_notes,
            metadata_json=json_safe(quality.metadata),
        )
        session.add(row)
        await session.flush()
        return row


async def provider_health_snapshot(settings: Settings) -> list[dict[str, object]]:
    """Run non-secret health probes concurrently; failures remain structured state."""

    clients = build_provider_clients(settings)
    providers: tuple[_HealthProvider, ...] = (
        clients.fred,
        clients.bls,
        clients.federal_reserve,
        clients.trading_economics,
        clients.databento,
        clients.ecb,
        clients.boj,
        clients.boe,
        clients.china,
    )
    results = await asyncio.gather(
        *(provider.healthcheck() for provider in providers),
        return_exceptions=True,
    )
    checked_at = datetime.now(UTC).isoformat()
    output: list[dict[str, object]] = []
    for provider, result in zip(providers, results, strict=True):
        capabilities = provider.get_capabilities()
        if isinstance(result, BaseException):
            status = "unavailable"
            message: str | None = type(result).__name__
            latency_ms = None
            warnings: list[str] = []
        else:
            status = str(result.status)
            message = result.message
            latency_ms = result.latency_ms
            warnings = list(result.warnings)
        output.append(
            {
                "provider_key": provider.key,
                "status": status,
                "message": message,
                "latency_ms": latency_ms,
                "warnings": warnings,
                "checked_at": checked_at,
                "capabilities": list(capabilities.operations),
                "paid_access": capabilities.paid_access,
                "terms": capabilities.metadata.get("terms_url"),
            }
        )
    return output


async def persist_configured_provider_health(
    engine: AsyncEngine,
    settings: Settings,
    *,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    """Persist a quota-free provider configuration snapshot.

    A daily health task must not consume a licensed calendar request merely to
    prove that a key string exists.  Successful provider runs remain the only
    persisted evidence of live health; this snapshot records public access or
    configured-but-unverified state with an explicit zero request count.
    """

    timestamp = checked_at or datetime.now(UTC)
    timestamp = (
        timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
    )
    clients = build_provider_clients(settings)
    definitions: tuple[tuple[_HealthProvider, bool, bool], ...] = (
        (clients.fred, settings.fred_api_key is not None, False),
        (clients.bls, True, True),
        (clients.federal_reserve, True, True),
        (
            clients.trading_economics,
            settings.trading_economics_api_key is not None,
            False,
        ),
        (clients.databento, settings.databento_api_key is not None, False),
    )
    items: list[dict[str, object]] = []
    for provider, configured, public in definitions:
        status = (
            "available_public"
            if public
            else "configured_unverified"
            if configured
            else "not_configured"
        )
        warning = (
            "No live request was performed; successful synchronization is the live-health evidence."
        )
        if provider.key == "trading_economics":
            warning = (
                "Trading Economics live probe skipped to avoid silent quota consumption; "
                "successful consensus synchronization is the live-health evidence."
            )
        run = await record_provider_run(
            engine,
            provider_key=provider.key,
            operation="configuration_health_snapshot",
            idempotency_key=f"provider-health:{provider.key}:{timestamp.date().isoformat()}",
            input_data={"network_probe": False, "checked_at": timestamp},
            terms_url=str(provider.get_capabilities().metadata.get("terms_url") or "") or None,
            started_at=timestamp,
        )
        await complete_provider_run(
            engine,
            run.id,
            records_read=0,
            records_written=1,
            request_count=0,
            output_data={
                "health_status": status,
                "configured": configured,
                "public_access": public,
                "network_probe": False,
                "checked_at": timestamp,
            },
            warnings=[warning],
            quality_grade="UNKNOWN",
            completed_at=timestamp,
        )
        items.append(
            {
                "provider_key": provider.key,
                "status": status,
                "configured": configured,
                "network_probe": False,
                "request_count": 0,
            }
        )
    return {
        "status": "completed",
        "records_read": 0,
        "records_written": len(items),
        "network_requests": 0,
        "items": items,
    }


__all__ = [
    "ProviderClients",
    "build_provider_clients",
    "persist_configured_provider_health",
    "persist_provider_artifact",
    "persist_quality_record",
    "provider_health_snapshot",
]
