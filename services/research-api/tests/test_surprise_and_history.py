from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from worldstate.event_engine.surprise import (
    calculate_bundle_surprise,
    calculate_indicator_surprise,
    calculate_nfp_bundle_surprise,
    calculate_policy_bundle_surprise,
)
from worldstate.event_engine.types import (
    HistoricalCase,
    HistoricalSurpriseObservation,
    IndicatorInput,
)
from worldstate.macro_core.regimes import derive_regime
from worldstate.research_engine.history import compare_historical_events


def indicator(
    key: str,
    actual: str,
    consensus: str,
    *,
    previous: str = "0.2",
    revised: str = "0.2",
    hotter_when_higher: bool = True,
    weight: float = 1,
) -> IndicatorInput:
    return IndicatorInput(
        key,
        key,
        Decimal(actual),
        Decimal(consensus),
        Decimal(previous),
        Decimal(revised),
        weight,
        hotter_when_higher,
    )


def test_indicator_orients_unemployment_and_revision() -> None:
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
    assert result.raw_surprise == Decimal("0.2")
    assert result.direction == "cold"
    assert result.revision == Decimal("-0.1")


def test_z_score_requires_minimum_and_excludes_future() -> None:
    current_at = datetime(2025, 1, 1, tzinfo=UTC)
    observations = [
        HistoricalSurpriseObservation(current_at - timedelta(days=index + 1), 0.1)
        for index in range(20)
    ]
    observations.append(HistoricalSurpriseObservation(current_at + timedelta(days=1), 99.0))
    result = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.3"),
        historical_raw=observations,
        current_release_at=current_at,
    )
    assert result.history_sample_count == 20
    assert result.surprise_z is None
    assert result.z_score_unavailable_reason == "historical_variance_is_zero"
    assert result.threshold_scaled_surprise == pytest.approx(4.0)


def test_z_score_is_genuine_when_history_has_variance() -> None:
    at = datetime(2025, 1, 1, tzinfo=UTC)
    history = [
        HistoricalSurpriseObservation(at - timedelta(days=index + 1), (index - 10) / 100)
        for index in range(20)
    ]
    result = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.3"), historical_raw=history, current_release_at=at
    )
    assert result.surprise_z is not None
    assert result.surprise_method == "z_score"


def test_z_score_is_null_below_declared_sample_minimum() -> None:
    at = datetime(2025, 1, 1, tzinfo=UTC)
    history = [
        HistoricalSurpriseObservation(at - timedelta(days=index + 1), (index - 9) / 100)
        for index in range(19)
    ]
    result = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.3"), historical_raw=history, current_release_at=at
    )
    assert result.history_sample_count == 19
    assert result.history_cutoff_at == at
    assert result.surprise_z is None
    assert result.threshold_scaled_surprise == pytest.approx(4.0)
    assert result.z_score_unavailable_reason == "minimum_20_historical_samples_required"


def test_missing_and_untimestamped_point_in_time_surprises_are_explicit() -> None:
    missing = calculate_indicator_surprise(
        IndicatorInput(
            "headline_mom",
            "headline_mom",
            None,
            Decimal("0.3"),
            Decimal("0.2"),
            None,
            1.0,
        )
    )
    assert missing.direction == "missing"
    at = datetime(2025, 1, 1, tzinfo=UTC)
    legacy = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.3"),
        historical_raw=[0.1] * 25,
        current_release_at=at,
    )
    assert legacy.history_sample_count == 0
    assert legacy.surprise_z is None
    assert legacy.z_score_unavailable_reason == "point_in_time_history_missing_timestamps"


def test_legacy_tuple_nan_and_zero_consensus_paths_are_bounded() -> None:
    at = datetime(2025, 1, 1, tzinfo=UTC)
    result = calculate_indicator_surprise(
        indicator("statement_tone_score", "0.2", "0", previous="0", revised="0"),
        historical_raw=[(at - timedelta(days=index + 1), (index - 10) / 100) for index in range(20)]
        + [(at - timedelta(days=30), float("nan"))],
        current_release_at=at,
    )
    assert result.relative_surprise is None
    assert result.history_sample_count == 20
    assert result.surprise_z is not None
    legacy = calculate_indicator_surprise(
        indicator("headline_mom", "0.4", "0.3"), historical_raw=[0.0, 0.1]
    )
    assert legacy.history_sample_count == 2


@pytest.mark.parametrize(
    ("values", "expected_direction"),
    [
        (("0.4", "3.4", "0.4", "3.4"), "hot"),
        (("0.2", "3.2", "0.2", "3.2"), "cold"),
        (("0.4", "3.4", "0.2", "3.2"), "mixed"),
        (("0.4", "3.2", "0.4", "3.2"), "hot"),
    ],
)
def test_cpi_classification_branches(
    values: tuple[str, str, str, str], expected_direction: str
) -> None:
    keys = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
    consensus = ("0.3", "3.3", "0.3", "3.3")
    result = calculate_bundle_surprise(
        [
            indicator(key, actual, expected)
            for key, actual, expected in zip(keys, values, consensus, strict=True)
        ]
    )
    assert result.direction == expected_direction
    assert result.classification


@pytest.mark.parametrize(
    ("value", "expected_direction"),
    [("0.5", "hot"), ("-0.5", "cold"), ("0", "mixed")],
)
def test_policy_bundle_directions(value: str, expected_direction: str) -> None:
    result = calculate_policy_bundle_surprise(
        [indicator("statement_tone_score", value, "0", previous="0", revised="0")]
    )
    assert result.direction == expected_direction


def test_empty_bundle_has_no_composite_score() -> None:
    result = calculate_bundle_surprise([])
    assert result.score is None
    assert result.composite_method == "insufficient"


@pytest.mark.parametrize(
    "values",
    [
        ("0.4", "3.2", "0.4", "3.4"),
        ("0.2", "3.4", "0.2", "3.2"),
        ("0.3", "3.3", "0.3", "3.3"),
    ],
)
def test_cpi_core_hot_cold_and_in_line_branches(values: tuple[str, str, str, str]) -> None:
    keys = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
    consensus = ("0.3", "3.3", "0.3", "3.3")
    result = calculate_bundle_surprise(
        [
            indicator(key, actual, expected)
            for key, actual, expected in zip(keys, values, consensus, strict=True)
        ]
    )
    assert result.classification


def test_missing_bundle_component_uses_missing_component_scale() -> None:
    missing = IndicatorInput(
        "headline_mom",
        "headline_mom",
        None,
        Decimal("0.3"),
        None,
        None,
        1.0,
    )
    result = calculate_bundle_surprise([missing])
    assert result.score is None
    assert result.component_methods["headline_mom"] == "missing"


def test_cpi_missing_component_does_not_claim_comprehensive_hot() -> None:
    result = calculate_bundle_surprise(
        [
            indicator("headline_mom", "0.4", "0.3"),
            indicator("headline_yoy", "3.4", "3.3"),
            indicator("core_mom", "0.4", "0.3"),
        ]
    )
    assert result.classification == "数据不足"
    assert result.composite_method == "threshold_only"


def test_nfp_revision_is_normalized_before_weighting() -> None:
    result = calculate_nfp_bundle_surprise(
        [
            indicator("nonfarm_payrolls", "200", "150", previous="150", revised="200", weight=1),
            indicator(
                "unemployment_rate",
                "4.0",
                "4.1",
                previous="4.1",
                revised="4.0",
                hotter_when_higher=False,
                weight=1,
            ),
        ]
    )
    analysis = result.revision_analysis
    assert analysis["method"] == "weighted_per_indicator_standardization"
    assert result.revision_dominant is False
    rows = cast(list[dict[str, object]], analysis["component_contributions"])
    assert abs(cast(float, rows[0]["revision_surprise_scaled"])) == pytest.approx(2.5)
    assert abs(cast(float, rows[1]["revision_surprise_scaled"])) == pytest.approx(2.0)
    assert analysis["dominance_comparison_available"] is False
    assert result.classification == "存在显著前值修正，但无法完成跨指标标准化比较"


def test_nfp_revision_dominance_requires_and_accepts_real_z_scales() -> None:
    at = datetime(2025, 1, 1, tzinfo=UTC)
    inputs = [
        indicator("nonfarm_payrolls", "151", "150", previous="100", revised="150"),
        indicator(
            "unemployment_rate",
            "4.09",
            "4.1",
            previous="4.2",
            revised="4.1",
            hotter_when_higher=False,
        ),
    ]
    history = {
        "nonfarm_payrolls": [
            HistoricalSurpriseObservation(at - timedelta(days=i + 1), float(i - 10))
            for i in range(20)
        ],
        "unemployment_rate": [
            HistoricalSurpriseObservation(at - timedelta(days=i + 1), (i - 10) / 100)
            for i in range(20)
        ],
    }
    result = calculate_nfp_bundle_surprise(
        inputs,
        historical_surprises=history,
        current_release_at=at,
    )
    assert result.revision_analysis["dominance_comparison_available"] is True
    assert result.revision_dominant is True


@pytest.mark.parametrize(
    ("growth", "wages", "include_growth", "include_wages"),
    [
        (1, 1, True, True),
        (-1, -1, True, True),
        (1, -1, True, True),
        (1, 0, True, False),
        (-1, 0, True, False),
        (0, 1, False, True),
        (0, -1, False, True),
        (0, 0, True, True),
    ],
)
def test_nfp_direction_classification_branches(
    growth: int,
    wages: int,
    include_growth: bool,
    include_wages: bool,
) -> None:
    inputs: list[IndicatorInput] = []
    if include_growth:
        inputs.extend(
            [
                indicator(
                    "nonfarm_payrolls",
                    str(150 + 50 * growth),
                    "150",
                    previous="150",
                    revised="150",
                ),
                indicator(
                    "unemployment_rate",
                    str(4.1 - 0.2 * growth),
                    "4.1",
                    previous="4.1",
                    revised="4.1",
                    hotter_when_higher=False,
                ),
            ]
        )
    if include_wages:
        inputs.extend(
            [
                indicator(
                    "average_hourly_earnings_mom",
                    str(0.3 + 0.1 * wages),
                    "0.3",
                    previous="0.3",
                    revised="0.3",
                ),
                indicator(
                    "average_hourly_earnings_yoy",
                    str(3.5 + 0.2 * wages),
                    "3.5",
                    previous="3.5",
                    revised="3.5",
                ),
            ]
        )
    result = calculate_nfp_bundle_surprise(inputs)
    assert result.classification


def historical_cases(count: int) -> list[HistoricalCase]:
    return [
        HistoricalCase(
            f"event-{index}",
            datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=index),
            "hot",
            "hot",
            "moderate",
            "hot",
            ("inflation:hot",),
            "none",
            True,
            {"gold_gc:post_5m": (-1) ** index * 0.1},
            "US_CPI",
            {"inflation_regime": "hot"},
            f"run-{index}",
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
def test_historical_sample_thresholds(count: int, mode: str, has_probability: bool) -> None:
    current = HistoricalCase(
        "current",
        datetime(2030, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "none",
        True,
        {"gold_gc:post_5m": 0.2},
        "US_CPI",
        {"inflation_regime": "hot"},
    )
    result = compare_historical_events(
        current, historical_cases(count), current_returns={"gold_gc:post_5m": 0.2}
    )
    metric = cast(dict[str, dict[str, object]], result["metrics"])["gold_gc:post_5m"]
    assert result["mode"] == mode
    assert ("up_probability" in metric) is has_probability


def test_missing_regime_is_not_full_similarity_and_high_contamination_is_excluded() -> None:
    current = HistoricalCase(
        "current",
        datetime(2030, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "none",
        True,
        release_type="US_CPI",
    )
    candidate = HistoricalCase(
        "past",
        datetime(2020, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "none",
        True,
        release_type="US_CPI",
    )
    contaminated = HistoricalCase(
        "dirty",
        datetime(2021, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "high",
        False,
        release_type="US_CPI",
    )
    result = compare_historical_events(current, [candidate, contaminated], current_returns={})
    similar_cases = cast(list[dict[str, object]], result["similar_cases"])
    detail = cast(dict[str, object], similar_cases[0]["match_detail"])
    assert detail["reliability"] == "reduced"
    assert "inflation_regime" in cast(list[str], detail["missing_dimensions"])
    assert result["contaminated_sample_count"] == 1


def test_regime_and_contamination_dimensions_report_their_contribution() -> None:
    current = HistoricalCase(
        "current",
        datetime(2030, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "low",
        True,
        release_type="US_CPI",
        regime_dimensions={"inflation_regime": "hot", "policy_cycle": "restrictive"},
    )
    same = HistoricalCase(
        "same",
        datetime(2020, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "low",
        True,
        release_type="US_CPI",
        regime_dimensions={"inflation_regime": "hot", "policy_cycle": "restrictive"},
    )
    different = HistoricalCase(
        "different",
        datetime(2021, 1, 1, tzinfo=UTC),
        "hot",
        "hot",
        "moderate",
        "hot",
        (),
        "medium",
        True,
        release_type="US_CPI",
        regime_dimensions={"inflation_regime": "cold", "policy_cycle": "easing"},
    )
    result = compare_historical_events(current, [different, same], current_returns={})
    rows = cast(list[dict[str, object]], result["similar_cases"])
    assert rows[0]["event_id"] == "same"
    assert cast(float, rows[0]["similarity"]) > cast(float, rows[1]["similarity"])
    detail = cast(dict[str, object], rows[1]["match_detail"])
    scores = cast(list[dict[str, object]], detail["dimension_scores"])
    inflation = next(item for item in scores if item["dimension"] == "inflation_regime")
    contamination = next(item for item in scores if item["dimension"] == "contamination")
    assert inflation["reason"] == "different"
    assert contamination["reason"] == "different"
    assert "contamination" in cast(list[str], detail["used_dimensions"])


def test_regime_uses_pre_event_context_and_excludes_post_event_returns() -> None:
    context: dict[str, object] = {
        "two_year_yield": 4.5,
        "two_year_yield_change_20": -0.3,
        "ten_year_yield": 4.1,
        "ten_year_real_yield": 1.8,
        "broad_dollar_index_change_20_percent": 1.2,
        "vix_close": 27.0,
    }
    first = derive_regime(
        release_type="US_CPI",
        bundle_direction="hot",
        surprise_score=2.0,
        returns={"dollar_dxy:post_5m": 2.0, "sp500_es:post_5m": -2.0},
        macro_context=context,
    )
    second = derive_regime(
        release_type="US_CPI",
        bundle_direction="cold",
        surprise_score=-2.0,
        returns={"dollar_dxy:post_5m": -3.0, "sp500_es:post_5m": 3.0},
        macro_context=context,
    )
    assert first.dimensions == second.dimensions
    assert first.dimensions["monetary_policy_regime"] == "high_but_easing"
    assert first.dimensions["growth_regime"] == "inverted_slowdown_risk"
    assert first.dimensions["real_yield_regime"] == "high"
    assert first.dimensions["dollar_regime"] == "strong"
    assert first.dimensions["risk_regime"] == "risk_off"
    assert any(item["rule"] == "outcome_leakage_guard" for item in first.evidence)
