"""Pre-declared, point-in-time historical matching for macro releases."""

from __future__ import annotations

import hashlib
import json
from statistics import mean, median
from typing import cast

from worldstate.event_engine.types import REGIME_DIMENSIONS, HistoricalCase

ROBUST_SAMPLE = 30
LIMITED_STATISTICAL_SAMPLE = 15
CASE_STUDY_SAMPLE = 5
CONTAMINATION_POLICY = "exclude_high_penalize_mismatch_v1"
DIMENSION_WEIGHTS = {
    "direction": 0.35,
    "core_direction": 0.20,
    "magnitude_bucket": 0.25,
    "regime": 0.20,
    "contamination": 0.10,
}


def magnitude_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    absolute = abs(score)
    return "small" if absolute < 0.75 else "moderate" if absolute < 2.0 else "large"


def _sample_mode(size: int) -> tuple[str, str]:
    if size >= ROBUST_SAMPLE:
        return "robust_statistics", "high"
    if size >= LIMITED_STATISTICAL_SAMPLE:
        return "limited_statistics", "low"
    if size >= CASE_STUDY_SAMPLE:
        return "case_studies", "descriptive_only"
    return "insufficient", "none"


def _regime_scores(
    current: HistoricalCase, candidate: HistoricalCase
) -> tuple[list[dict[str, object]], float, list[str]]:
    output: list[dict[str, object]] = []
    available_score = available_weight = 0.0
    missing: list[str] = []
    for dimension in REGIME_DIMENSIONS:
        left = current.regime_dimensions.get(dimension, "unknown")
        right = candidate.regime_dimensions.get(dimension, "unknown")
        available = left != "unknown" and right != "unknown"
        score = 1.0 if available and left == right else 0.0
        weight = 1 / len(REGIME_DIMENSIONS)
        row = {
            "dimension": dimension,
            "current_value": left,
            "candidate_value": right,
            "available": available,
            "weight": weight,
            "score": score,
            "reason": "equal" if score else "different" if available else "missing",
        }
        output.append(row)
        if available:
            available_weight += weight
            available_score += weight * score
        else:
            missing.append(dimension)
    return output, available_score / available_weight if available_weight else 0.0, missing


def _similarity(
    current: HistoricalCase, candidate: HistoricalCase
) -> tuple[float, dict[str, object]]:
    dimensions: list[dict[str, object]] = []
    for key in ("direction", "core_direction", "magnitude_bucket"):
        weight = DIMENSION_WEIGHTS[key]
        same = getattr(current, key) == getattr(candidate, key)
        dimensions.append(
            {
                "dimension": key,
                "current_value": getattr(current, key),
                "candidate_value": getattr(candidate, key),
                "available": True,
                "weight": weight,
                "score": 1.0 if same else 0.0,
                "reason": "equal" if same else "different",
            }
        )
    regime_rows, regime_score, missing = _regime_scores(current, candidate)
    regime_available = len(missing) < len(REGIME_DIMENSIONS)
    dimensions.extend(
        [
            {**row, "weight": DIMENSION_WEIGHTS["regime"] / len(REGIME_DIMENSIONS)}
            for row in regime_rows
        ]
    )
    contamination_available = bool(current.contamination_level) and bool(
        candidate.contamination_level
    )
    same_contamination = (
        current.clean_window == candidate.clean_window
        and current.contamination_level == candidate.contamination_level
    )
    dimensions.append(
        {
            "dimension": "contamination",
            "current_value": current.contamination_level,
            "candidate_value": candidate.contamination_level,
            "available": contamination_available,
            "weight": DIMENSION_WEIGHTS["contamination"],
            "score": 1.0 if same_contamination else 0.0,
            "reason": "equal" if same_contamination else "different",
        }
    )
    weighted = DIMENSION_WEIGHTS["direction"] * (
        1 if current.direction == candidate.direction else 0
    )
    weighted += DIMENSION_WEIGHTS["core_direction"] * (
        1 if current.core_direction == candidate.core_direction else 0
    )
    weighted += DIMENSION_WEIGHTS["magnitude_bucket"] * (
        1 if current.magnitude_bucket == candidate.magnitude_bucket else 0
    )
    effective_weight = sum(
        DIMENSION_WEIGHTS[key] for key in ("direction", "core_direction", "magnitude_bucket")
    )
    if regime_available:
        weighted += DIMENSION_WEIGHTS["regime"] * regime_score
        effective_weight += DIMENSION_WEIGHTS["regime"]
    if contamination_available:
        weighted += DIMENSION_WEIGHTS["contamination"] * (1 if same_contamination else 0)
        effective_weight += DIMENSION_WEIGHTS["contamination"]
    similarity = weighted / effective_weight if effective_weight else 0.0
    used = [str(row["dimension"]) for row in dimensions if cast(bool, row["available"])]
    return round(similarity, 4), {
        "used_dimensions": sorted(set(used)),
        "missing_dimensions": missing,
        "dimension_scores": dimensions,
        "effective_weight": round(effective_weight, 4),
        "reliability": "reduced" if missing else "normal",
    }


def compare_historical_events(
    current: HistoricalCase,
    candidates: list[HistoricalCase],
    *,
    current_returns: dict[str, float | None],
) -> dict[str, object]:
    """Use a fixed non-post-hoc recipe and exclude future/high-contamination cases."""
    pool = [
        case
        for case in candidates
        if case.event_id != current.event_id
        and case.release_type == current.release_type
        and case.release_at < current.release_at
    ]
    filter_steps: list[dict[str, object]] = [
        {
            "condition": f"release_type = {current.release_type}; release_at < current",
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
    high_contaminated = [
        case for case in pool if case.contamination_level == "high" or not case.clean_window
    ]
    pool = [case for case in pool if case not in high_contaminated]
    filter_steps.append(
        {
            "condition": CONTAMINATION_POLICY,
            "before": before,
            "after": len(pool),
            "excluded_high_contamination": len(high_contaminated),
        }
    )
    ranked: list[dict[str, object]] = []
    for case in pool:
        similarity, detail = _similarity(current, case)
        ranked.append(
            {
                "event_id": case.event_id,
                "analysis_run_id": case.analysis_run_id,
                "release_at": case.release_at.isoformat(),
                "classification": case.classification,
                "similarity": similarity,
                "clean_window": case.clean_window,
                "contamination_level": case.contamination_level,
                "returns": case.returns,
                "match_detail": detail,
                "is_fixture": case.is_fixture,
                "proxy_instrument_count": case.proxy_instrument_count,
            }
        )
    ranked.sort(key=lambda row: cast(float, row["similarity"]), reverse=True)
    mode, reliability = _sample_mode(len(pool))
    metrics: dict[str, dict[str, object]] = {}
    for key in sorted({key for case in pool for key in case.returns}):
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
                    "current_percentile": 100
                    * sum(value <= current_value for value in sample)
                    / len(sample)
                    if current_value is not None
                    else None,
                }
            )
        else:
            metric.update(
                {
                    "probability_suppressed": True,
                    "suppression_reason": "minimum_15_samples_required",
                }
            )
        metrics[key] = metric
    manifest = [
        {
            "release_id": case.event_id,
            "analysis_run_id": case.analysis_run_id,
            "fixture": case.is_fixture,
        }
        for case in pool
    ]
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    fixture_count = sum(case.is_fixture for case in pool)
    proxy_count = sum(case.proxy_instrument_count > 0 for case in pool)
    warning = (
        "history sample is insufficient for statistical conclusions"
        if mode == "insufficient"
        else None
    )
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
        "filter_recipe": "macro-history-v0.5-mode-isolated",
        "contamination_policy": CONTAMINATION_POLICY,
        "filters": filter_steps,
        "metrics": metrics,
        "similar_cases": ranked[:8],
        "warning": warning,
        "sample_manifest_hash": manifest_hash,
        "sample_manifest": manifest,
        "sample_release_ids": [case.event_id for case in pool],
        "sample_analysis_run_ids": [case.analysis_run_id for case in pool if case.analysis_run_id],
        "fixture_sample_count": fixture_count,
        "observed_sample_count": len(pool) - fixture_count,
        "contaminated_sample_count": len(high_contaminated),
        "proxy_sample_count": proxy_count,
    }
