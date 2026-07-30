from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from macro_engine.data_quality import DataQuality, QualityGrade, quality_score
from macro_engine.event_lab.explanation import build_structured_explanation
from macro_engine.event_lab.fixtures import CPI_FIXTURES, INSTRUMENTS, generate_fixture_bars
from macro_engine.event_lab.history import compare_historical_events, magnitude_bucket
from macro_engine.event_lab.macrosynergy_adapter import MacrosynergyAdapter
from macro_engine.event_lab.surprise import (
    calculate_bundle_surprise,
    calculate_indicator_surprise,
)
from macro_engine.event_lab.types import (
    ComputedWindow,
    EarliestReaction,
    HistoricalCase,
    IndicatorInput,
    WindowSpec,
)
from macro_engine.event_lab.windows import calculate_event_windows, detect_earliest_reaction
from macro_engine.market_data import (
    BarQuery,
    CsvMarketBarProvider,
    FixtureMarketBarProvider,
    MarketBarRecord,
    MarketInstrumentRef,
    ProviderWaterfall,
)


def indicator(
    key: str,
    actual: str | None,
    consensus: str | None,
    *,
    previous: str = "0.3",
    revised: str = "0.3",
) -> IndicatorInput:
    return IndicatorInput(
        key=key,
        title=key,
        actual=Decimal(actual) if actual is not None else None,
        consensus=Decimal(consensus) if consensus is not None else None,
        previous=Decimal(previous),
        revised_previous=Decimal(revised),
        weight=0.25,
    )


def bundle_for(
    actuals: tuple[str, str, str, str],
    consensus: tuple[str, str, str, str] = ("0.2", "3.0", "0.3", "3.7"),
    *,
    previous: str = "0.3",
    revised: str = "0.3",
):
    keys = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
    return calculate_bundle_surprise(
        [
            indicator(
                key,
                actual,
                expected,
                previous=previous,
                revised=revised,
            )
            for key, actual, expected in zip(keys, actuals, consensus, strict=True)
        ]
    )


@pytest.mark.parametrize(
    ("actuals", "expected"),
    [
        (("0.3", "3.2", "0.4", "3.9"), "全面偏热"),
        (("0.1", "2.8", "0.2", "3.5"), "全面偏冷"),
        (("0.3", "3.2", "0.2", "3.5"), "Headline与Core方向冲突"),
        (("0.3", "2.8", "0.4", "3.5"), "月率和年率方向冲突"),
        (("0.2", "3.0", "0.4", "3.9"), "核心通胀偏热"),
        (("0.2", "3.0", "0.3", "3.7"), "大体符合预期"),
    ],
)
def test_cpi_bundle_classifications(
    actuals: tuple[str, str, str, str],
    expected: str,
) -> None:
    assert bundle_for(actuals).classification == expected


def test_surprise_handles_history_missing_and_revision_dominance() -> None:
    result = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.2"),
        historical_raw=[0.05, -0.05, 0.1, -0.1, 0.0],
    )
    assert result.raw == Decimal("0.2")
    assert result.standardized is not None
    assert result.history_samples == 5

    missing = calculate_indicator_surprise(indicator("headline_mom", None, "0.2"))
    assert missing.direction == "missing"
    assert missing.raw is None

    revised = bundle_for(
        ("0.21", "3.01", "0.31", "3.71"),
        previous="0.1",
        revised="0.5",
    )
    assert revised.classification == "主要变化来自前值修正"
    assert revised.revision_dominant is True


def instrument_ref(*, proxy: bool = False) -> MarketInstrumentRef:
    return MarketInstrumentRef(
        canonical_key="gold_gc",
        symbol="GC",
        title="Gold",
        exchange="COMEX",
        quote_unit="USD/oz",
        is_proxy=proxy,
        proxy_for="yield" if proxy else None,
    )


def query() -> BarQuery:
    return BarQuery(
        instrument=instrument_ref(),
        start=datetime(2024, 2, 13, 13, 29, tzinfo=UTC),
        end=datetime(2024, 2, 13, 13, 32, tzinfo=UTC),
        interval_seconds=60,
    )


@pytest.mark.asyncio
async def test_csv_fixture_and_waterfall_providers_preserve_quality_and_warnings() -> None:
    csv_text = """timestamp,instrument_key,open,high,low,close,volume,interval_seconds
2024-02-13T13:30:00Z,gold_gc,2000,2002,1999,2001,10,60
2024-02-13T13:30:00Z,gold_gc,2001,2003,2000,2002,11,60
2024-02-13 13:31:00,gold_gc,2002,2004,2001,2003,12,60
2024-02-13T13:31:00Z,other,1,1,1,1,1,60
"""
    provider = CsvMarketBarProvider(
        csv_text,
        acquired_at=datetime(2024, 2, 14, tzinfo=UTC),
        verified=True,
    )
    batch = await provider.fetch_bars(query())
    assert len(batch.bars) == 1
    assert batch.bars[0].close_value == Decimal("2002")
    assert len(batch.warnings) == 2
    assert batch.quality.quality_grade == QualityGrade.B
    assert batch.quality.to_storage()["source_type"] == "csv_import"

    fixture = FixtureMarketBarProvider(
        {"gold_gc": batch.bars},
        source_name="test fixture",
        acquired_at=datetime(2024, 2, 14, tzinfo=UTC),
    )
    fixture_batch = await fixture.fetch_bars(query())
    assert fixture_batch.quality.is_fixture
    assert fixture_batch.bars

    class BrokenProvider:
        key = "broken"

        async def fetch_bars(self, _query: BarQuery):
            raise RuntimeError("offline")

    waterfall = ProviderWaterfall([BrokenProvider(), fixture])
    resolved = await waterfall.fetch_bars(query())
    assert resolved.provider_key == "fixture"
    assert resolved.warnings[0].startswith("broken:")

    empty = FixtureMarketBarProvider({}, source_name="empty")
    empty_result = await ProviderWaterfall([empty]).fetch_bars(query())
    assert empty_result.bars == []
    assert empty_result.quality.missing_reason == "fixture_has_no_rows"

    with pytest.raises(RuntimeError, match="no market-bar provider"):
        await ProviderWaterfall([BrokenProvider()]).fetch_bars(query())


def test_market_bar_validation_and_batch_boundaries() -> None:
    with pytest.raises(ValidationError, match="high must"):
        MarketBarRecord(
            instrument_key="gold_gc",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            interval_seconds=60,
            open_value=Decimal(10),
            high_value=Decimal(9),
            low_value=Decimal(8),
            close_value=Decimal(10),
            volume=Decimal(1),
            source_symbol="GC",
        )
    with pytest.raises(ValidationError, match="volume cannot be negative"):
        MarketBarRecord(
            instrument_key="gold_gc",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            interval_seconds=60,
            open_value=Decimal(10),
            high_value=Decimal(11),
            low_value=Decimal(9),
            close_value=Decimal(10),
            volume=Decimal(-1),
            source_symbol="GC",
        )


def test_windows_detect_reversal_missing_horizon_and_earliest_observation() -> None:
    fixture = next(item for item in CPI_FIXTURES if item.event_key == "us-cpi-2024-02-13")
    silver = next(item for item in INSTRUMENTS if item["canonical_key"] == "silver_si")
    bars = generate_fixture_bars(fixture, silver)
    windows = calculate_event_windows(
        bars,
        release_at=fixture.release_at,
        interval_seconds=60,
        source_grade="C",
    )
    by_key = {item.key: item for item in windows}
    assert by_key["post_1m"].return_percent is not None
    assert by_key["post_5m"].return_percent is not None
    assert by_key["post_5m"].direction_reversal
    assert by_key["next_close"].missing_reason == "incomplete_session_or_long_horizon_coverage"
    assert not by_key["next_close"].direction_reversal

    earliest = detect_earliest_reaction(
        "silver_si",
        bars,
        release_at=fixture.release_at,
        interval_seconds=60,
    )
    assert earliest is not None
    assert earliest.granularity_seconds == 60
    assert "不能区分同一bar内" in earliest.limitation

    assert (
        detect_earliest_reaction(
            "silver_si",
            bars[:5],
            release_at=fixture.release_at,
            interval_seconds=60,
        )
        is None
    )
    missing = calculate_event_windows(
        [],
        release_at=fixture.release_at,
        interval_seconds=60,
        source_grade="A",
        specs=(WindowSpec("post_5m", "five", 0, 300),),
    )[0]
    assert missing.direction == "missing"
    assert missing.quality_grade == "D"


def historical_case(
    event_id: str,
    *,
    direction: str = "hot",
    core: str = "hot",
    magnitude: str = "moderate",
    value: float = -0.5,
) -> HistoricalCase:
    return HistoricalCase(
        event_id=event_id,
        release_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=int(event_id)),
        classification="全面偏热",
        direction=direction,
        magnitude_bucket=magnitude,
        core_direction=core,
        regime_tags=("high_rates",),
        contamination_level="none",
        clean_window=True,
        returns={"gold_gc:post_5m": value},
    )


def test_history_uses_fixed_filters_and_enforces_minimum_sample() -> None:
    current = historical_case("0", value=-0.8)
    candidates = [current, *(historical_case(str(i), value=-0.1 * i) for i in range(1, 7))]
    result = compare_historical_events(
        current,
        candidates,
        current_returns=current.returns,
    )
    assert result["mode"] == "statistics"
    assert result["post_filter_count"] == 6
    metrics = result["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["gold_gc:post_5m"]["sample_size"] == 6
    assert metrics["gold_gc:post_5m"]["current_percentile"] is not None

    degraded = compare_historical_events(
        current,
        candidates[:3],
        current_returns=current.returns,
    )
    assert degraded["mode"] == "case_studies"
    assert degraded["warning"]
    assert magnitude_bucket(None) == "unknown"
    assert magnitude_bucket(0.2) == "small"
    assert magnitude_bucket(1.0) == "moderate"
    assert magnitude_bucket(3.0) == "large"


def computed_window(value: float, *, reversal: bool = False) -> ComputedWindow:
    now = datetime(2024, 2, 13, 13, 30, tzinfo=UTC)
    return ComputedWindow(
        key="post_5m",
        label="T0至T+5分钟",
        start_at=now,
        end_at=now + timedelta(minutes=5),
        start_value=Decimal("100"),
        end_value=Decimal(str(100 + value)),
        change_absolute=Decimal(str(value)),
        return_percent=value,
        max_up_percent=max(0.0, value),
        max_down_percent=min(0.0, value),
        realized_volatility=0.1,
        volume_change_percent=20,
        coverage_ratio=1.0,
        direction="up" if value > 0 else "down",
        spike_fade=False,
        dip_recovery=False,
        direction_reversal=reversal,
        granularity_seconds=60,
        quality_grade="B",
    )


def test_explanation_separates_facts_rules_competition_and_limits() -> None:
    bundle = bundle_for(("0.3", "3.2", "0.4", "3.9"))
    windows = {
        "dollar_dxy": {"post_5m": computed_window(0.3)},
        "gold_gc": {"post_5m": computed_window(0.2, reversal=True)},
        "silver_si": {"post_5m": computed_window(-0.8)},
        "sp500_es": {"post_5m": computed_window(-0.5)},
        "nasdaq_nq": {"post_5m": computed_window(-0.7)},
        "ust2y_zt": {"post_5m": computed_window(-0.2)},
        "ust10y_zn": {"post_5m": computed_window(0.1)},
    }
    earliest = [
        EarliestReaction(
            instrument_key="dollar_dxy",
            detected_at=datetime(2024, 2, 13, 13, 31, tzinfo=UTC),
            lag_seconds=60,
            move_percent=0.1,
            direction="up",
            threshold_percent=0.02,
            pre_event_volatility=0.01,
            granularity_seconds=60,
            confirmation_bars=2,
            limitation="minute bars",
        )
    ]
    explanation = build_structured_explanation(
        event_title="US CPI",
        bundle=bundle,
        windows=windows,
        earliest=earliest,
        contamination_level="high",
        clean_window=False,
        quality_grades=["A", "B"],
        is_fixture=True,
        historical={"mode": "case_studies"},
    )
    rules = {row["rule"] for row in explanation["explanations"]}
    assert {
        "inflation_hotter_policy_path",
        "safe_haven_overrides_rates",
        "curve_divergence",
        "event_contamination",
    } <= rules
    assert explanation["confidence"] <= 0.62
    assert "不能使用强因果措辞" in explanation["report"]
    assert len(explanation["data_gaps"]) == 4


def test_quality_scoring_and_optional_macrosynergy_boundary() -> None:
    assert quality_score("A") == 1.0
    assert quality_score("invalid") == quality_score(QualityGrade.UNKNOWN)
    quality = DataQuality(
        source_name="manual",
        source_type="manual_actual",
        acquired_at=datetime(2024, 1, 1, tzinfo=UTC),
        quality_grade=QualityGrade.C,
    )
    assert quality.score == quality_score("C")
    adapter = MacrosynergyAdapter()
    assert adapter.status()["boundary"] == "worldstate_adapter_v1"
    records = adapter.to_quantamental_records(
        [("gold_gc", datetime(2024, 1, 1, tzinfo=UTC).date(), 1.2)],
        category="EVENT_RET",
    )
    assert records[0]["cid"] == "GOLD_GC"
    if not adapter.available:
        with pytest.raises(RuntimeError, match="not installed"):
            adapter.historical_volatility(
                [
                    ("gold_gc", datetime(2024, 1, 1, tzinfo=UTC).date(), float(index))
                    for index in range(30)
                ]
            )
