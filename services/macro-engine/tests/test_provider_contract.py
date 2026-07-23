from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime

from macro_engine.domain.enums import ProviderStatus
from macro_engine.domain.models import (
    ObservationRecord,
    ProviderHealth,
    ReleaseRecord,
    SeriesMetadata,
    SeriesSearchResult,
)
from macro_engine.providers.base import MacroProvider


class FixtureProvider:
    key = "fixture"

    async def search_series(self, query: str, *, limit: int = 25) -> Sequence[SeriesSearchResult]:
        return [SeriesSearchResult(native_id=query, title="Fixture")][:limit]

    async def fetch_metadata(self, native_id: str) -> SeriesMetadata:
        return SeriesMetadata(
            native_id=native_id,
            title="Fixture",
            frequency="monthly",
            unit="index",
            source_url="https://example.test/fixture",
        )

    async def fetch_observations(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> AsyncIterator[ObservationRecord]:
        records: list[ObservationRecord] = []
        for record in records:
            yield record

    async def fetch_vintages(self, native_id: str) -> Sequence[date]:
        return [date(2026, 1, 1)]

    async def fetch_releases(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Sequence[ReleaseRecord]:
        return []

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
        )


async def test_runtime_provider_protocol_and_normalized_metadata() -> None:
    provider = FixtureProvider()

    assert isinstance(provider, MacroProvider)
    metadata = await provider.fetch_metadata("TEST")
    assert metadata.native_id == "TEST"
    assert metadata.model_config["frozen"] is True
    assert (await provider.healthcheck()).status is ProviderStatus.OK
