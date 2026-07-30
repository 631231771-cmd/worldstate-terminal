"""Pre-declared historical matching and sample-safe event statistics."""

from __future__ import annotations

from statistics import mean, median
from typing import cast

from macro_engine.event_lab.types import HistoricalCase

MIN_STATISTICAL_SAMPLE = 5


def magnitude_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    absolute = abs(score)
    if absolute < 0.75:
        return "small"
    if absolute < 2.0:
        return "moderate"
    return "large"


def _similarity(current: HistoricalCase, candidate: HistoricalCase) -> float:
    score = 0.0
    score += 0.35 if current.direction == candidate.direction else 0.0
    score += 0.2 if current.core_direction == candidate.core_direction else 0.0
    score += 0.25 if current.magnitude_bucket == candidate.magnitude_bucket else 0.0
    left = set(current.regime_tags)
    right = set(candidate.regime_tags)
    union = left | right
    score += 0.2 * (len(left & right) / len(union) if union else 1.0)
    return round(score, 4)


def compare_historical_events(
    current: HistoricalCase,
    candidates: list[HistoricalCase],
    *,
    current_returns: dict[str, float | None],
    minimum_sample: int = MIN_STATISTICAL_SAMPLE,
) -> dict[str, object]:
    """Apply one fixed filter recipe and refuse probability output when too small."""

    pool = [case for case in candidates if case.event_id != current.event_id]
    filter_steps: list[dict[str, object]] = [
        {
            "condition": "event_type = US_CPI",
            "before": len(pool),
            "after": len(pool),
        }
    ]

    before = len(pool)
    pool = [case for case in pool if case.direction == current.direction]
    filter_steps.append(
        {
            "condition": f"composite_direction = {current.direction}",
            "before": before,
            "after": len(pool),
        }
    )
    before = len(pool)
    pool = [case for case in pool if case.core_direction == current.core_direction]
    filter_steps.append(
        {
            "condition": f"core_direction = {current.core_direction}",
            "before": before,
            "after": len(pool),
        }
    )
    filter_steps.append(
        {
            "condition": (
                f"magnitude_bucket = {current.magnitude_bucket} "
                "(ranking condition; no post-hoc sample reduction)"
            ),
            "before": len(pool),
            "after": len(pool),
        }
    )

    ranked = sorted(
        (
            {
                "event_id": case.event_id,
                "release_at": case.release_at.isoformat(),
                "classification": case.classification,
                "similarity": _similarity(current, case),
                "clean_window": case.clean_window,
                "contamination_level": case.contamination_level,
                "returns": case.returns,
            }
            for case in pool
        ),
        key=lambda row: cast(float, row["similarity"]),
        reverse=True,
    )
    reliable = len(pool) >= minimum_sample
    metrics: dict[str, dict[str, object]] = {}
    all_keys = sorted({key for case in pool for key in case.returns})
    for key in all_keys:
        sample = [float(value) for case in pool if (value := case.returns.get(key)) is not None]
        if len(sample) < minimum_sample:
            metrics[key] = {
                "sample_size": len(sample),
                "reliable": False,
                "reason": f"minimum_{minimum_sample}_samples_required",
            }
            continue
        current_value = current_returns.get(key)
        percentile = (
            100 * sum(value <= current_value for value in sample) / len(sample)
            if current_value is not None
            else None
        )
        metrics[key] = {
            "sample_size": len(sample),
            "reliable": True,
            "mean": mean(sample),
            "median": median(sample),
            "up_probability": sum(value > 0 for value in sample) / len(sample),
            "current_percentile": percentile,
            "minimum_sample": minimum_sample,
        }

    return {
        "mode": "statistics" if reliable else "case_studies",
        "reliable": reliable,
        "minimum_sample": minimum_sample,
        "pre_filter_count": len(candidates),
        "post_filter_count": len(pool),
        "filter_recipe": "cpi-history-v1",
        "filters": filter_steps,
        "metrics": metrics,
        "similar_cases": ranked[:8],
        "warning": (None if reliable else "样本不足，仅展示案例；不输出概率、百分位或统计性结论。"),
    }
