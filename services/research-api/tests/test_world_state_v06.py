from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from worldstate.application.market_research_service import _transform
from worldstate.application.world_state_service import (
    SeriesSignal,
    aggregate_dimension,
    calculate_signal,
    classify_regime,
    load_point_in_time_observations,
)
from worldstate.db.base import Base
from worldstate.db.models import EconomicEntity, Observation, Provider, Series
from worldstate.db.session import create_engine


def test_state_signal_is_bounded_and_orientation_aware() -> None:
    score, momentum, gap = calculate_signal([100, 101, 103, 106, 110, 115], orientation=1)
    assert gap is None
    assert -1 <= (score or 0) <= 1
    assert -1 <= (momentum or 0) <= 1
    inverted, _, _ = calculate_signal([100, 101, 103, 106, 110, 115], orientation=-1)
    assert inverted is not None
    assert score is not None
    assert inverted * score <= 0


def test_state_signal_reports_insufficient_history_and_zero_variance() -> None:
    score, momentum, gap = calculate_signal([1, 1], minimum_history=3)
    assert score is None
    assert momentum is None
    assert gap
    score, momentum, gap = calculate_signal([10, 10, 10, 10], minimum_history=3)
    assert score == 0
    assert momentum == 0
    assert gap is None


def test_state_history_uses_one_latest_vintage_per_period(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'pit.db').as_posix()}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        series_id = uuid.uuid4()
        first_available = datetime(2026, 1, 10, tzinfo=UTC)
        revised_available = datetime(2026, 2, 10, tzinfo=UTC)
        async with factory() as session, session.begin():
            provider = Provider(
                key="pit-test", name="PIT Test", base_url="https://example.test", enabled=True
            )
            entity = EconomicEntity(iso3="TST", name="Test", entity_type="country")
            session.add_all([provider, entity])
            await session.flush()
            session.add(
                Series(
                    id=series_id,
                    provider_id=provider.id,
                    entity_id=entity.id,
                    native_id="TEST",
                    canonical_key="TST.GROWTH.TEST",
                    title="Test series",
                    frequency="monthly",
                    unit="index",
                    observation_type="official_series",
                    source_url="https://example.test/series",
                    availability_method="provider_realtime_start",
                    availability_precision="day",
                    default_transform="level",
                    active=True,
                    metadata_json={},
                )
            )
            await session.flush()
            session.add_all(
                [
                    Observation(
                        series_id=series_id,
                        period_start=date(2025, 12, 1),
                        period_end=date(2025, 12, 1),
                        value=Decimal("100"),
                        vintage_date=first_available.date(),
                        available_at=first_available,
                        availability_method="provider_realtime_start",
                        availability_precision="day",
                        fetched_at=first_available,
                        data_mode="observed",
                        quality_flags=[],
                        source_hash="first",
                    ),
                    Observation(
                        series_id=series_id,
                        period_start=date(2025, 12, 1),
                        period_end=date(2025, 12, 1),
                        value=Decimal("105"),
                        vintage_date=revised_available.date(),
                        available_at=revised_available,
                        availability_method="provider_realtime_start",
                        availability_precision="day",
                        fetched_at=revised_available,
                        data_mode="observed",
                        quality_flags=[],
                        source_hash="revision",
                    ),
                    Observation(
                        series_id=series_id,
                        period_start=date(2026, 1, 1),
                        period_end=date(2026, 1, 1),
                        value=Decimal("110"),
                        vintage_date=revised_available.date(),
                        available_at=revised_available,
                        availability_method="provider_realtime_start",
                        availability_precision="day",
                        fetched_at=revised_available,
                        data_mode="observed",
                        quality_flags=[],
                        source_hash="next-period",
                    ),
                    # Imported after the revision but carrying an older
                    # availability timestamp. Persist order must not override
                    # the genuinely later-known vintage.
                    Observation(
                        series_id=series_id,
                        period_start=date(2025, 12, 1),
                        period_end=date(2025, 12, 1),
                        value=Decimal("99"),
                        vintage_date=date(2026, 1, 15),
                        available_at=datetime(2026, 1, 15, tzinfo=UTC),
                        availability_method="provider_realtime_start",
                        availability_precision="day",
                        fetched_at=revised_available + timedelta(days=1),
                        data_mode="observed",
                        quality_flags=[],
                        source_hash="late-import-of-older-vintage",
                    ),
                ]
            )
        async with factory() as session:
            before_revision = await load_point_in_time_observations(
                session,
                series_id=series_id,
                as_of=first_available + timedelta(days=1),
                data_mode="observed",
            )
            latest = await load_point_in_time_observations(
                session,
                series_id=series_id,
                as_of=revised_available + timedelta(days=1),
                data_mode="observed",
            )
        assert [item.value for item in before_revision] == [Decimal("100")]
        assert [item.value for item in latest] == [Decimal("105"), Decimal("110")]
        await engine.dispose()

    asyncio.run(scenario())


def test_dimension_freshness_uses_covered_period_not_recent_fetch_time() -> None:
    signal = SeriesSignal(
        series_key="CHN.GROWTH.TEST",
        title="Old current-public series",
        dimension="growth",
        score=0.2,
        momentum=0.1,
        latest_value=100.0,
        period_start=date.today() - timedelta(days=365),
        available_at=datetime.now(UTC),
        observation_count=24,
        provider_key="fred_alfred",
        source_url="https://example.test",
        data_mode="observed",
        quality="B",
        missing_reason=None,
        evidence_ids=("observation:test",),
        freshness_half_life_days=45.0,
    )
    result = aggregate_dimension([signal])
    assert result["freshness"] < 0.001
    assert result["confidence"] < 0.5


def test_regime_label_does_not_treat_positive_as_unconditionally_good() -> None:
    result = classify_regime(
        {
            "growth": {"score": -0.6, "confidence": 0.8},
            "inflation": {"score": 0.7, "confidence": 0.8},
            "policy_tightness": {"score": 0.5, "confidence": 0.7},
            "risk": {"score": 0.4, "confidence": 0.7},
        }
    )
    assert "滞胀" in result["label"]
    assert "政策偏紧" in result["tags"]
    assert "风险规避" in result["tags"]


def test_world_state_endpoint_is_explicit_about_demo_data(client: TestClient) -> None:
    response = client.get("/v2/world-state?data_mode=fixture")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "fixture"
    assert payload["methodology_version"] == "wst-state-v1"
    assert payload["dimensions"]["growth"]["coverage"] > 0
    assert payload["dimensions"]["growth"]["top_drivers"][0]["data_mode"] == "fixture"
    observed = client.get("/v2/world-state?data_mode=observed").json()
    assert observed["data_mode"] == "observed"
    assert all(
        item["data_mode"] == "observed"
        for dimension in observed["dimensions"].values()
        for item in dimension["top_drivers"]
    )


def test_daily_brief_is_deterministic_and_has_explicit_sections(client: TestClient) -> None:
    response = client.get("/v2/daily-brief?data_mode=fixture")
    assert response.status_code == 200
    payload = response.json()
    assert payload["methodology_version"] == "wst-daily-brief-v1"
    assert payload["world_state"]["data_mode"] == "fixture"
    assert isinstance(payload["biggest_changes"], list)
    assert isinstance(payload["upcoming"], list)
    assert "AI 只可在此基础上解释" in payload["ai_note"]


def test_series_transforms_preserve_missing_leads() -> None:
    points = _transform([100, 101, 102, 104, 108], [], "mom")
    assert points[0] is None
    assert points[-1] is not None
    zscores = _transform([1, 1, 1, 2], [], "zscore")
    assert zscores[-1] is not None
    assert zscores[-1] > 0


def test_market_and_series_endpoints_are_mode_explicit(client: TestClient) -> None:
    market = client.get("/v2/market-dashboard?horizon=1w&data_mode=fixture")
    assert market.status_code == 200
    assert market.json()["methodology_version"] == "wst-market-dashboard-v1"
    series = client.get("/v2/series?data_mode=fixture")
    assert series.status_code == 200
    assert all(item["data_mode"] == "fixture" for item in series.json())
    detail = client.get("/v2/series/US.INFLATION.CPI_HEADLINE?data_mode=fixture&transform=mom")
    assert detail.status_code == 200
    assert detail.json()["transform"] == "mom"
    assert detail.json()["points"]


def test_thesis_book_is_user_owned_and_evaluation_does_not_auto_confirm(client: TestClient) -> None:
    created = client.post(
        "/v2/theses",
        json={
            "title": "增长放缓但金融条件稳定",
            "thesis": "未来三个月美国增长继续放缓，但金融条件暂时不会明显恶化。",
            "horizon": "3m",
            "related_states": ["growth", "risk"],
            "watch_variables": ["US.GROWTH.INDUSTRIAL_PRODUCTION"],
            "confirmation_conditions": ["增长状态继续走弱"],
            "falsification_conditions": ["风险状态显著恶化"],
        },
    )
    assert created.status_code == 200, created.text
    thesis_id = created.json()["id"]
    listed = client.get("/v2/theses").json()
    assert any(item["id"] == thesis_id for item in listed)
    evaluated = client.get(f"/v2/theses/{thesis_id}/evaluate")
    assert evaluated.status_code == 200
    assert "不自动修改用户观点" in evaluated.json()["interpretation"]
    updated = client.patch(f"/v2/theses/{thesis_id}", json={"confidence": 0.7})
    assert updated.status_code == 200
    assert updated.json()["confidence"] == 0.7
    assistant = client.post(
        "/v2/research/assistant/context",
        json={"question": "最近通胀是变热还是变冷？", "data_mode": "fixture"},
    )
    assert assistant.status_code == 200
    assert assistant.json()["mode"] == "deterministic_context"
    assert assistant.json()["facts"][0]["claim_type"] == "fact"


def test_global_macro_marks_uncovered_countries_unavailable(client: TestClient) -> None:
    response = client.get("/v2/global-macro?data_mode=observed")
    assert response.status_code == 200
    payload = response.json()
    assert {item["iso3"] for item in payload["countries"]} == {"USA", "CHN", "EA19", "JPN", "GBR"}
    assert all(item["data_mode"] == "observed" for item in payload["countries"])
    assert any(item["status"] == "unavailable" for item in payload["countries"])
    assert payload["context_cards"]
