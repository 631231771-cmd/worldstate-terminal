from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from worldstate.event_engine.surprise import (
    calculate_bundle_surprise,
    calculate_indicator_surprise,
)
from worldstate.event_engine.types import HistoricalCase, IndicatorInput
from worldstate.research_engine.history import compare_historical_events


def indicator(
    key: str,
    actual: str,
    consensus: str,
    *,
    previous: str = "0.2",
    revised: str = "0.2",
    hotter_when_higher: bool = True,
) -> IndicatorInput:
    return IndicatorInput(
        key=key,
        title=key,
        actual=Decimal(actual),
        consensus=Decimal(consensus),
        previous=Decimal(previous),
        revised_previous=Decimal(revised),
        weight=1,
        hotter_when_higher=hotter_when_higher,
    )


def test_indicator_surprise_orients_unemployment_and_revision() -> None:
    result = calculate_indicator_surprise(
        indicator(
            "unemployment_rate",
            "4.2",
            "4.0",
            previous="4.1",
            revised="4.0",
            hotter_when_higher=False,
        )
    )
    assert result.raw == Decimal("0.2")
    assert result.direction == "cold"
    assert result.revision == Decimal("-0.1")


def test_cpi_bundle_detects_conflict_and_revision_dominance() -> None:
    conflict = calculate_bundle_surprise(
        [
            indicator("headline_mom", "0.4", "0.3"),
            indicator("headline_yoy", "3.4", "3.3"),
            indicator("core_mom", "0.2", "0.3"),
            indicator("core_yoy", "3.7", "3.8"),
        ]
    )
    assert conflict.classification == "Headline与Core方向冲突"

    revised = calculate_bundle_surprise(
        [
            indicator(key, "0.31", "0.30", previous="0.1", revised="0.5")
            for key in ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
        ]
    )
    assert revised.revision_dominant is True
    assert revised.classification == "主要变化来自前值修正"


def historical_cases(count: int) -> list[HistoricalCase]:
    return [
        HistoricalCase(
            event_id=f"event-{index}",
            release_at=datetime(2020, 1, 1, tzinfo=UTC),
            classification="全面偏热",
            direction="hot",
            magnitude_bucket="moderate",
            core_direction="hot",
            regime_tags=("high_inflation",),
            contamination_level="none",
            clean_window=True,
            returns={"gold_gc:post_5m": (-1) ** index * 0.1},
        )
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("count", "mode", "has_probability"),
    [
        (4, "insufficient", False),
        (10, "case_studies", False),
        (20, "limited_statistics", True),
        (35, "robust_statistics", True),
    ],
)
def test_historical_sample_thresholds(
    count: int,
    mode: str,
    has_probability: bool,
) -> None:
    current = historical_cases(1)[0]
    current = HistoricalCase(**{**current.__dict__, "event_id": "current"})
    result = compare_historical_events(
        current,
        historical_cases(count),
        current_returns={"gold_gc:post_5m": 0.2},
    )
    metrics = cast(dict[str, dict[str, object]], result["metrics"])
    metric = metrics["gold_gc:post_5m"]
    assert result["mode"] == mode
    assert ("up_probability" in metric) is has_probability
    assert ("current_percentile" in metric) is has_probability
