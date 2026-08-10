from datetime import date
from decimal import Decimal

import httpx
import pytest

from worldstate.provider_kit import OfficialPublicCsvProvider, ProviderTerms, PublicSeriesSpec


@pytest.mark.asyncio
async def test_ecb_sdmx_csv_is_normalized_with_retrieval_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("EXR/D.USD.EUR.SP00.A")
        return httpx.Response(
            200,
            text="KEY,TIME_PERIOD,OBS_VALUE\nA,2026-08-07,1.16\nA,2026-08-08,1.17\n",
            headers={"content-type": "text/csv"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OfficialPublicCsvProvider(
            key="ecb_data_portal",
            name="ECB",
            base_url="https://example.test/service/data",
            terms=ProviderTerms(
                license_name="ECB terms",
                terms_url="https://example.test/terms",
                redistribution_allowed=True,
            ),
            series=(
                PublicSeriesSpec(
                    native_id="EXR.D.USD.EUR.SP00.A",
                    canonical_key="EA.EXTERNAL.EURUSD",
                    title="EURUSD",
                    entity="EA19",
                    frequency="daily",
                    unit="USD_per_EUR",
                    source_url="https://example.test/series",
                ),
            ),
            client=client,
        )
        batch = await provider.fetch_observation_batch(
            "EXR.D.USD.EUR.SP00.A", start=date(2026, 8, 1), end=date(2026, 8, 9)
        )

    assert len(batch.observations) == 2
    assert batch.observations[-1].value == Decimal("1.17")
    assert batch.observations[-1].available_at is not None
    assert batch.quality.is_verified is True
    assert batch.quality.is_fixture is False
    assert batch.observations[0].period_start == date(2026, 8, 7)
    assert batch.artifacts[0].content_hash


@pytest.mark.asyncio
async def test_unconfigured_public_provider_is_explicitly_blocked() -> None:
    provider = OfficialPublicCsvProvider(
        key="boj_public",
        name="BOJ",
        base_url="",
        terms=ProviderTerms(license_name="BOJ", terms_url="https://example.test"),
        series=(),
        enabled=False,
    )
    health = await provider.healthcheck()
    assert str(health.status) == "not_configured"
