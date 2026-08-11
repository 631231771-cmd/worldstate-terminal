from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from worldstate.application.analysis_orchestrator import initialize_research_catalog
from worldstate.application.market_research_service import _continuity_segments
from worldstate.application.official_sync_service import _sync_derived_market_context
from worldstate.application.product_projection_service import _change_projection, _market_horizon
from worldstate.db.base import Base
from worldstate.db.models import MarketBar, MarketInstrument
from worldstate.db.session import create_engine


def _market_bar(
    instrument_id: uuid.UUID,
    *,
    provider: str,
    timestamp: datetime,
    value: str,
    source_symbol: str,
) -> MarketBar:
    return MarketBar(
        instrument_id=instrument_id,
        futures_contract_id=None,
        timestamp=timestamp,
        interval_seconds=86400,
        open_value=Decimal(value),
        high_value=Decimal(value),
        low_value=Decimal(value),
        close_value=Decimal(value),
        volume=None,
        provider_key=provider,
        source_symbol=source_symbol,
        contract_code="",
        is_regular_session=True,
        quality_id=None,
        fetched_at=timestamp,
        metadata_json={"context_only": True},
        data_mode="observed",
    )


def test_market_continuity_does_not_join_provider_segments() -> None:
    instrument_id = uuid.uuid4()
    instrument = MarketInstrument(
        id=instrument_id,
        canonical_key="test_market",
        symbol="TEST",
        title="Test market",
        asset_class="equity_index",
        instrument_type="index_context",
        exchange=None,
        quote_unit="index points",
        measurement_type="price_context",
        source_timezone="UTC",
        is_proxy=False,
        proxy_for=None,
        active=True,
        metadata_json={},
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        (
            _market_bar(
                instrument_id,
                provider="old",
                timestamp=start,
                value="100",
                source_symbol="OLD",
            ),
            instrument,
            None,
        ),
        (
            _market_bar(
                instrument_id,
                provider="old",
                timestamp=start + timedelta(days=1),
                value="101",
                source_symbol="OLD",
            ),
            instrument,
            None,
        ),
        (
            _market_bar(
                instrument_id,
                provider="new",
                timestamp=start + timedelta(days=1),
                value="200",
                source_symbol="NEW",
            ),
            instrument,
            None,
        ),
        (
            _market_bar(
                instrument_id,
                provider="new",
                timestamp=start + timedelta(days=2),
                value="202",
                source_symbol="NEW",
            ),
            instrument,
            None,
        ),
    ]
    active, segments = _continuity_segments(rows)
    assert [float(row[0].close_value) for row in active] == [202.0, 200.0]
    assert len(segments) == 2
    assert segments[0]["provider"] == "new"
    assert segments[0]["active"] is True


def test_derived_curve_bars_persist_formula_and_inputs(tmp_path) -> None:
    async def scenario() -> None:
        engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'derived.db').as_posix()}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await initialize_research_catalog(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        timestamp = datetime(2026, 8, 7, tzinfo=UTC)
        async with factory() as session, session.begin():
            instruments = {
                row.canonical_key: row
                for row in (
                    await session.scalars(
                        select(MarketInstrument).where(
                            MarketInstrument.canonical_key.in_(
                                {
                                    "ust2y_yield_context",
                                    "ust3m_yield_context",
                                    "ust10y_yield_context",
                                }
                            )
                        )
                    )
                ).all()
            }
            for key, value, symbol in (
                ("ust2y_yield_context", "4.10", "DGS2"),
                ("ust3m_yield_context", "3.90", "DGS3MO"),
                ("ust10y_yield_context", "4.60", "DGS10"),
            ):
                session.add(
                    _market_bar(
                        instruments[key].id,
                        provider="fred_alfred",
                        timestamp=timestamp,
                        value=value,
                        source_symbol=symbol,
                    )
                )
        assert await _sync_derived_market_context(engine, calculated_at=timestamp) == 2
        async with factory() as session:
            rows = (
                await session.execute(
                    select(MarketBar, MarketInstrument)
                    .join(MarketInstrument, MarketInstrument.id == MarketBar.instrument_id)
                    .where(MarketBar.provider_key == "worldstate_derived")
                    .order_by(MarketInstrument.canonical_key)
                )
            ).all()
        values_by_key = {
            row[1].canonical_key: float(row[0].close_value) for row in rows
        }
        assert values_by_key == {
            "curve_2s10s_derived": 0.5,
            "curve_3m10y_derived": 0.7,
        }
        assert all(row[0].metadata_json["derived"] is True for row in rows)
        assert all(len(row[0].metadata_json["input_bar_ids"]) == 2 for row in rows)
        assert {row[0].metadata_json["calculation_version"] for row in rows} == {
            "market-derived-v1"
        }
        await engine.dispose()

    asyncio.run(scenario())


def test_capability_inventory_is_mode_explicit_and_actionable(client: TestClient) -> None:
    response = client.get("/v2/data/capabilities", params={"data_mode": "observed"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "observed"
    assert "CURRENT_STATE" in payload["summary"]
    assert "EVENT_INTRADAY" in payload["summary"]
    assert isinstance(payload["items"], list)
    for item in payload["items"][:5]:
        assert {"dataset_key", "rows", "capabilities", "data_mode"} <= set(item)
        assert "CURRENT_STATE" in item["capabilities"]


def test_today_projection_uses_product_labels_and_valid_session_changes(client: TestClient) -> None:
    response = client.get("/v2/product/today", params={"data_mode": "observed"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "observed"
    assert {
        "macro_snapshot",
        "markets",
        "what_changed",
        "global",
        "capability_summary",
    } <= set(payload)
    for item in payload["markets"]:
        assert "formatted_value" in item
        assert item["change_unit"] in {"%", "bp"}
        assert item["details"]["canonical_key"] == item["key"]
    if payload["markets"]:
        assert all("window_semantics" not in item for item in payload["markets"])


def test_macro_projection_keeps_canonical_dimension_keys(client: TestClient) -> None:
    payload = client.get("/v2/product/today", params={"data_mode": "observed"}).json()
    for country in payload["global"]:
        for key, dimension in country["dimensions"].items():
            assert key in {
                "growth",
                "inflation",
                "liquidity",
                "policy_tightness",
                "credit",
                "risk",
                "fiscal",
                "external",
            }
            assert dimension["label"]
        for key in country["available_dimensions"]:
            assert key in country["dimensions"]


def test_markets_projection_returns_all_horizons_in_one_response(client: TestClient) -> None:
    response = client.get("/v2/product/markets", params={"data_mode": "observed"})
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert set(item.get("horizons", {})) <= {"1d", "1w", "1m", "3m"}


def test_market_horizon_contract_normalizes_price_percent_without_double_scaling() -> None:
    point = _market_horizon(
        {"instrument_key": "gold_gc", "change_percent": 5.0, "change_unit": "percent"}
    )
    assert point == {"value": 5.0, "unit": "%", "direction": "up"}


def test_market_horizon_contract_normalizes_rates_to_basis_points() -> None:
    point = _market_horizon(
        {"instrument_key": "ust10y_yield_context", "change_value": 0.05, "change_unit": "bp"}
    )
    assert point == {"value": 5.0, "unit": "bp", "direction": "up"}


def test_product_events_projection_exposes_server_ordered_views(client: TestClient) -> None:
    response = client.get("/v2/product/events", params={"data_mode": "observed", "limit": 100})
    assert response.status_code == 200
    payload = response.json()
    assert {"items", "upcoming", "recent", "default_event_id"} <= set(payload)
    upcoming = payload["upcoming"]
    assert all(item["status"] == "scheduled" for item in upcoming)
    assert [item["scheduled_at"] for item in upcoming] == sorted(
        item["scheduled_at"] for item in upcoming
    )
    if payload["default_event_id"] is not None:
        assert any(item["id"] == payload["default_event_id"] for item in payload["items"])


def test_change_projection_does_not_repeat_dimension_label() -> None:
    change = _change_projection(
        {
            "what_changed": "inflation state is weak",
            "why_it_matters": "inflation 的主要驱动是 crude oil",
            "magnitude": -0.4,
        }
    )
    assert change["what"] == "通胀 state is weak"
    assert change["why"] == " 的主要驱动是 crude oil"


def test_product_event_detail_uses_product_route(client: TestClient) -> None:
    events = client.get("/v2/product/events", params={"data_mode": "all", "limit": 1}).json()
    event_id = events["items"][0]["id"]
    response = client.get(f"/v2/product/events/{event_id}", params={"data_mode": "all"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == event_id
    assert payload["event"]["id"] == event_id
    assert payload["supported_indicators"]
    assert {"expectations", "actual", "surprise", "market_reaction", "analysis", "actions"} <= set(
        payload
    )
    assert all(
        item["key"] not in {"headline_cpi_mom", "target_rate_upper"}
        for item in payload["supported_indicators"]
    )
