"""Pre-declared historical matching with explicit sample-size reliability."""

from __future__ import annotations

from statistics import mean, median
from typing import cast

from worldstate.event_engine.types import HistoricalCase

ROBUST_SAMPLE = 30
LIMITED_STATISTICAL_SAMPLE = 15
CASE_STUDY_SAMPLE = 5


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


def _sample_mode(size: int) -> tuple[str, str]:
    if size >= ROBUST_SAMPLE:
        return "robust_statistics", "high"
    if size >= LIMITED_STATISTICAL_SAMPLE:
        return "limited_statistics", "low"
    if size >= CASE_STUDY_SAMPLE:
        return "case_studies", "descriptive_only"
    return "insufficient", "none"


def compare_historical_events(
    current: HistoricalCase,
    candidates: list[HistoricalCase],
    *,
    current_returns: dict[str, float | None],
) -> dict[str, object]:
    """Use a fixed recipe and suppress probability output for small samples."""

    pool = [
        case
        for case in candidates
        if case.event_id != current.event_id and case.release_type == current.release_type
    ]
    filter_steps: list[dict[str, object]] = [
        {
            "condition": f"release_type = {current.release_type}",
            "before": len(candidates),
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
            "condition": f"component_direction = {current.core_direction}",
            "before": before,
            "after": len(pool),
        }
    )
    filter_steps.append(
        {
            "condition": (
                f"magnitude_bucket = {current.magnitude_bucket} "
                "(ranking only; never post-hoc sample reduction)"
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
    mode, reliability = _sample_mode(len(pool))
    metrics: dict[str, dict[str, object]] = {}
    all_keys = sorted({key for case in pool for key in case.returns})
    for key in all_keys:
        sample = [float(value) for case in pool if (value := case.returns.get(key)) is not None]
        sample_mode, sample_reliability = _sample_mode(len(sample))
        metric: dict[str, object] = {
            "sample_size": len(sample),
            "mode": sample_mode,
            "reliability": sample_reliability,
        }
        if len(sample) >= CASE_STUDY_SAMPLE:
            metric.update(
                {
                    "mean": mean(sample),
                    "median": median(sample),
                    "minimum": min(sample),
                    "maximum": max(sample),
                }
            )
        if len(sample) >= LIMITED_STATISTICAL_SAMPLE:
            current_value = current_returns.get(key)
            metric.update(
                {
                    "up_probability": sum(value > 0 for value in sample) / len(sample),
                    "current_percentile": (
                        100 * sum(value <= current_value for value in sample) / len(sample)
                        if current_value is not None
                        else None
                    ),
                }
            )
        else:
            metric["probability_suppressed"] = True
            metric["suppression_reason"] = "minimum_15_samples_required"
        metrics[key] = metric

    warning = None
    if mode == "limited_statistics":
        warning = "样本为15至29个：显示概率和百分位，但可靠性标记为低。"
    elif mode == "case_studies":
        warning = "样本为5至14个：仅作描述性案例展示，不输出概率或百分位。"
    elif mode == "insufficient":
        warning = "样本少于5个：不输出统计结论，仅保留可追溯的单个案例。"
    return {
        "mode": mode,
        "reliability": reliability,
        "thresholds": {
            "robust": ROBUST_SAMPLE,
            "limited_statistics": LIMITED_STATISTICAL_SAMPLE,
            "case_studies": CASE_STUDY_SAMPLE,
        },
        "pre_filter_count": len(candidates),
        "post_filter_count": len(pool),
        "filter_recipe": "macro-history-v3-fixed",
        "filters": filter_steps,
        "metrics": metrics,
        "similar_cases": ranked[:8],
        "warning": warning,
    }
