"""The public workbench never upgrades context into event evidence."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from worldstate.application.data_foundation_service import record_provider_run
from worldstate.application.market_workbench_service import market_factors, parse_official_feed
from worldstate.application.official_evidence_service import persist_export
from worldstate.db.base import Base
from worldstate.db.session import create_engine
from worldstate.provider_kit.official_evidence import EvidencePoint
from worldstate.provider_kit.public_quotes import empty_quotes


def test_feed_requires_official_https_and_never_accepts_doctype() -> None:
    xml = b"""<rss><channel>
      <item><title>Federal Reserve issues statement</title>
        <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm</link>
        <pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item>
      <item><title>Injected source</title><link>https://evil.example/article</link></item>
    </channel></rss>"""
    items = parse_official_feed(
        xml, source="Federal Reserve", topic="policy",
        retrieved_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    assert len(items) == 1
    assert items[0]["published_at"] == "2026-09-16T18:00:00+00:00"
    assert items[0]["source"] == "Federal Reserve"
    with pytest.raises(ValueError, match="unexpected"):
        parse_official_feed(
            b"<!DOCTYPE rss><rss/>", source="EIA", topic="energy",
            retrieved_at=datetime(2026, 9, 17, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_oil_factor_uses_only_persisted_observed_context(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'workbench.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    run = await record_provider_run(
        engine, provider_key="eia_official", operation="workbench-test", idempotency_key="one"
    )
    await persist_export(
        engine,
        dataset="eia_balance", provider_key="eia_official",
        url="https://ir.eia.gov/wpsr/table1.csv", content=b"verified test fixture",
        content_type="text/csv", retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
        points=[EvidencePoint(
            "eia.production", "US crude production", date(2026, 9, 11), Decimal(13944),
            "thousand_barrels_per_day", "weekly",
        )],
        run_id=run.id,
    )
    result = await market_factors(engine, "oil")
    production = next(item for item in result["items"] if item["series_key"] == "eia.production")
    assert production["value"] == 13944
    assert production["frequency"] == "weekly"
    assert production["point_in_time"] is False
    assert production["observed"] is True
    stocks = next(item for item in result["items"] if item["series_key"] == "eia.crude_stocks")
    assert stocks["value"] is None
    await engine.dispose()


def test_display_quotes_include_market_watchlist_without_yield_conflation() -> None:
    quotes = {item.key: item for item in empty_quotes()}
    assert {"cl_quote", "es_quote", "nq_quote", "btc_quote", "dxy_quote"} <= quotes.keys()
    assert quotes["zt_quote"].kind == "futures"
    assert quotes["zn_quote"].change_unit == "%"
    assert quotes["us10y_quote"].change_unit == "bp"
    assert all(not item.event_research_eligible for item in quotes.values())
