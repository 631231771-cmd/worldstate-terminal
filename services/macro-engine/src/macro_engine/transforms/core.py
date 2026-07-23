"""Small, point-in-time-safe transforms used by the state engine."""

from __future__ import annotations

import math
from collections.abc import Sequence

Number = float | None


def _lag_for_year(frequency: str) -> int:
    return {
        "daily": 252,
        "weekly": 52,
        "monthly": 12,
        "quarterly": 4,
        "annual": 1,
    }.get(frequency.lower(), 12)


def lagged_change(values: Sequence[Number], lag: int, *, percent: bool) -> list[Number]:
    """Return a difference or percent change without filling missing observations."""

    output: list[Number] = [None] * len(values)
    for index in range(lag, len(values)):
        current = values[index]
        previous = values[index - lag]
        if current is None or previous is None:
            continue
        if percent:
            if previous == 0:
                continue
            output[index] = (current / previous - 1) * 100
        else:
            output[index] = current - previous
    return output


def moving_average(values: Sequence[Number], window: int) -> list[Number]:
    output: list[Number] = [None] * len(values)
    for index in range(window - 1, len(values)):
        sample = values[index - window + 1 : index + 1]
        if any(value is None for value in sample):
            continue
        output[index] = sum(value for value in sample if value is not None) / window
    return output


def rolling_quantile(values: Sequence[Number], window: int = 120) -> list[Number]:
    """Return the inclusive empirical percentile for each value."""

    output: list[Number] = [None] * len(values)
    for index, current in enumerate(values):
        if current is None:
            continue
        sample = [
            value for value in values[max(0, index - window + 1) : index + 1] if value is not None
        ]
        if len(sample) < min(12, window):
            continue
        less = sum(value < current for value in sample)
        equal = sum(value == current for value in sample)
        output[index] = (less + 0.5 * equal) / len(sample)
    return output


def rolling_zscore(values: Sequence[Number], window: int = 120) -> list[Number]:
    output: list[Number] = [None] * len(values)
    for index, current in enumerate(values):
        if current is None:
            continue
        sample = [
            value for value in values[max(0, index - window + 1) : index + 1] if value is not None
        ]
        if len(sample) < min(12, window):
            continue
        mean = sum(sample) / len(sample)
        variance = sum((value - mean) ** 2 for value in sample) / len(sample)
        if variance > 0:
            output[index] = (current - mean) / math.sqrt(variance)
    return output


def annualized_change(
    values: Sequence[Number],
    periods: int,
    periods_per_year: int = 12,
) -> list[Number]:
    output: list[Number] = [None] * len(values)
    for index in range(periods, len(values)):
        current = values[index]
        previous = values[index - periods]
        if current is None or previous is None or previous == 0 or current <= 0 or previous <= 0:
            continue
        output[index] = ((current / previous) ** (periods_per_year / periods) - 1) * 100
    return output


def binary_transform(
    left: Sequence[Number],
    right: Sequence[Number],
    operation: str,
) -> list[Number]:
    """Apply a same-date binary transform; callers align dates before invoking it."""

    output: list[Number] = []
    for first, second in zip(left, right, strict=False):
        if first is None or second is None:
            output.append(None)
        elif operation in {"spread", "real_rate"}:
            output.append(first - second)
        elif operation == "inversion":
            output.append(second - first)
        elif operation == "ratio":
            output.append(None if second == 0 else first / second)
        else:
            raise ValueError(f"unsupported binary transform: {operation}")
    return output


def apply_transform(
    values: Sequence[Number],
    transform: str,
    *,
    frequency: str = "monthly",
) -> list[Number]:
    """Apply a configured unary transform using only current and prior values."""

    normalized = transform.lower().replace("-", "_")
    if normalized in {"level", "raw"}:
        return list(values)
    if normalized in {"difference", "diff"}:
        return lagged_change(values, 1, percent=False)
    if normalized in {"percent_change", "pct_change"}:
        return lagged_change(values, 1, percent=True)
    if normalized == "yoy":
        return lagged_change(values, _lag_for_year(frequency), percent=True)
    if normalized == "qoq":
        lag = 1 if frequency.lower() == "quarterly" else 3
        return lagged_change(values, lag, percent=True)
    if normalized in {"annualized_3m", "3m_annualized"}:
        return annualized_change(values, 3)
    if normalized in {"annualized_6m", "6m_annualized"}:
        return annualized_change(values, 6)
    if normalized in {"moving_average", "ma"}:
        return moving_average(values, 3)
    if normalized in {"rolling_percentile", "rolling_quantile"}:
        return rolling_quantile(values)
    if normalized in {"rolling_zscore", "zscore"}:
        return rolling_zscore(values)
    raise ValueError(f"unsupported transform: {transform}")
