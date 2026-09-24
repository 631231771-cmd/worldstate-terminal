"""Event-relative market windows and earliest observed reaction detection."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from statistics import median, pstdev

from worldstate.event_engine.types import (
    ComputedWindow,
    EarliestReaction,
    WindowSpec,
)
from worldstate.market_core.sessions import (
    calendar_for_instrument,
    expected_tradable_bars,
    resolve_session_window_end,
)
from worldstate.provider_kit import MarketBarRecord

WINDOW_SPECS = (
    WindowSpec("pre_60m", "T-60分钟至T0", -3600, 0),
    WindowSpec("pre_15m", "T-15分钟至T0", -900, 0),
    WindowSpec("post_1m", "T0至T+1分钟", 0, 60),
    WindowSpec("post_5m", "T0至T+5分钟", 0, 300),
    WindowSpec("post_15m", "T0至T+15分钟", 0, 900),
    WindowSpec("post_30m", "T0至T+30分钟", 0, 1800),
    WindowSpec("post_60m", "T0至T+60分钟", 0, 3600),
    WindowSpec("post_4h", "T0至T+4小时", 0, 14400),
    WindowSpec("us_cash_close", "当日美国现货收盘", 0, 27000, True),
    WindowSpec("next_close", "下一交易日收盘", 0, 113400, True),
    WindowSpec("day_5_close", "五个交易日后收盘", 0, 545400, True),
)
MINUTE_WINDOW_SPECS = tuple(spec for spec in WINDOW_SPECS if not spec.session_based)
SESSION_CLOSE_WINDOW_SPECS = tuple(spec for spec in WINDOW_SPECS if spec.session_based)

_MIN_SIGNIFICANCE_PERCENT = {
    "gold_gc": 0.04,
    "silver_si": 0.06,
    "dollar_dxy": 0.015,
    "sp500_es": 0.03,
    "nasdaq_nq": 0.04,
    "ust2y_zt": 0.008,
    "ust10y_zn": 0.01,
}


def _percent_change(end: Decimal, start: Decimal) -> float | None:
    if start == 0:
        return None
    return float((end - start) / start * Decimal(100))


def _direction(value: float | None, tolerance: float = 0.0001) -> str:
    if value is None or abs(value) < tolerance:
        return "flat" if value is not None else "missing"
    return "up" if value > 0 else "down"


def _log_returns(values: list[Decimal]) -> list[float]:
    output: list[float] = []
    for previous, current in pairwise(values):
        if previous > 0 and current > 0:
            output.append(math.log(float(current / previous)))
    return output


def _quality_for_coverage(source_grade: str, coverage: float) -> str:
    if coverage >= 0.98:
        return source_grade
    if coverage >= 0.8:
        return "C" if source_grade in {"A", "B", "C"} else source_grade
    return "D"


def _calculate_one(
    bars: list[MarketBarRecord],
    *,
    release_at: datetime,
    spec: WindowSpec,
    interval_seconds: int,
    source_grade: str,
    pre_volume: float | None,
    instrument_key: str | None,
) -> ComputedWindow:
    start_at = release_at + timedelta(seconds=spec.start_seconds)
    end_at = (
        resolve_session_window_end(release_at, spec.key, instrument_key)
        if spec.session_based
        else release_at + timedelta(seconds=spec.end_seconds)
    )
    is_pre = spec.end_seconds <= 0
    if is_pre:
        sample = [bar for bar in bars if start_at <= bar.timestamp < release_at]
        start_value = sample[0].open_value if sample else None
    else:
        sample = [bar for bar in bars if release_at <= bar.timestamp <= end_at]
        baseline = [bar for bar in bars if bar.timestamp < release_at]
        start_value = baseline[-1].close_value if baseline else None

    expected = expected_tradable_bars(start_at, end_at, interval_seconds, instrument_key)
    coverage = min(1.0, len(sample) / expected)
    if not sample or start_value is None or (not spec.session_based and coverage < 1.0):
        return ComputedWindow(
            key=spec.key,
            label=spec.label,
            start_at=start_at,
            end_at=end_at,
            start_value=start_value,
            end_value=None,
            change_absolute=None,
            return_percent=None,
            max_up_percent=None,
            max_down_percent=None,
            realized_volatility=None,
            volume_change_percent=None,
            coverage_ratio=coverage,
            direction="missing",
            spike_fade=False,
            dip_recovery=False,
            direction_reversal=False,
            granularity_seconds=interval_seconds,
            quality_grade="D",
            missing_reason=(
                "session_calendar_or_long_horizon_bars_unavailable"
                if spec.session_based
                else ("incomplete_minute_window" if sample else "insufficient_bars")
            ),
            calendar_name=calendar_for_instrument(instrument_key),
            calendar_precision="exchange_session_lite",
            expected_tradable_bars=expected,
        )

    end_value = sample[-1].close_value
    return_percent = _percent_change(end_value, start_value)
    high_returns = [
        value
        for bar in sample
        if (value := _percent_change(bar.high_value, start_value)) is not None
    ]
    low_returns = [
        value
        for bar in sample
        if (value := _percent_change(bar.low_value, start_value)) is not None
    ]
    max_up = max(high_returns) if high_returns else None
    max_down = min(low_returns) if low_returns else None
    close_path = [start_value, *(bar.close_value for bar in sample)]
    minute_returns = _log_returns(close_path)
    realized = (
        pstdev(minute_returns) * math.sqrt(len(minute_returns)) * 100
        if len(minute_returns) >= 2
        else 0.0
    )
    volumes = [float(bar.volume) for bar in sample if bar.volume is not None]
    sample_volume = sum(volumes) / len(volumes) if volumes else None
    volume_change = None
    if sample_volume is not None and pre_volume is not None and pre_volume != 0:
        volume_change = (sample_volume / pre_volume - 1) * 100
    fade_floor = max(0.03, realized * 0.6)
    spike_fade = bool(
        max_up is not None
        and max_up > fade_floor
        and return_percent is not None
        and return_percent < max_up * 0.35
    )
    dip_recovery = bool(
        max_down is not None
        and max_down < -fade_floor
        and return_percent is not None
        and return_percent > max_down * 0.35
    )
    return ComputedWindow(
        key=spec.key,
        label=spec.label,
        start_at=start_at,
        end_at=end_at,
        start_value=start_value,
        end_value=end_value,
        change_absolute=end_value - start_value,
        return_percent=return_percent,
        max_up_percent=max_up,
        max_down_percent=max_down,
        realized_volatility=realized,
        volume_change_percent=volume_change,
        coverage_ratio=coverage,
        direction=_direction(return_percent),
        spike_fade=spike_fade,
        dip_recovery=dip_recovery,
        direction_reversal=False,
        granularity_seconds=interval_seconds,
        quality_grade=_quality_for_coverage(source_grade, coverage),
        missing_reason=(
            "incomplete_session_or_long_horizon_coverage"
            if spec.session_based and coverage < 0.8
            else None
        ),
        calendar_name=calendar_for_instrument(instrument_key),
        calendar_precision="exchange_session_lite",
        expected_tradable_bars=expected,
    )


def calculate_event_windows(
    bars: list[MarketBarRecord],
    *,
    release_at: datetime,
    interval_seconds: int,
    source_grade: str,
    specs: tuple[WindowSpec, ...] = WINDOW_SPECS,
    instrument_key: str | None = None,
) -> list[ComputedWindow]:
    """Compute all windows and flag direction changes against the first response."""

    ordered = sorted(bars, key=lambda item: item.timestamp)
    pre_bars = [
        bar
        for bar in ordered
        if release_at - timedelta(minutes=15) <= bar.timestamp < release_at
        and bar.volume is not None
    ]
    pre_volumes = [float(bar.volume) for bar in pre_bars if bar.volume is not None]
    pre_volume = sum(pre_volumes) / len(pre_volumes) if pre_volumes else None
    calculated = [
        _calculate_one(
            ordered,
            release_at=release_at,
            spec=spec,
            interval_seconds=interval_seconds,
            source_grade=source_grade,
            pre_volume=pre_volume,
            instrument_key=instrument_key,
        )
        for spec in specs
    ]
    return apply_direction_reversals(calculated)


def apply_direction_reversals(calculated: list[ComputedWindow]) -> list[ComputedWindow]:
    """Apply one shared short-response anchor across minute and long windows."""

    anchor = next(
        (
            item
            for key in ("post_1m", "post_5m")
            if (item := next((row for row in calculated if row.key == key), None))
            and item.direction in {"up", "down"}
        ),
        None,
    )
    if anchor is None:
        return calculated
    return [
        replace(
            row,
            direction_reversal=(
                row.key not in {"pre_60m", "pre_15m", anchor.key}
                and row.direction in {"up", "down"}
                and row.direction != anchor.direction
                and row.coverage_ratio >= 0.8
                and row.missing_reason is None
            ),
        )
        for row in calculated
    ]


def _missing_session_window(
    *,
    release_at: datetime,
    spec: WindowSpec,
    instrument_key: str | None,
    source_grade: str,
    reason: str,
    limitations: tuple[str, ...],
    experimental: bool,
    calendar_precision: str,
) -> ComputedWindow:
    end_at = resolve_session_window_end(release_at, spec.key, instrument_key)
    return ComputedWindow(
        key=spec.key,
        label=spec.label,
        start_at=release_at,
        end_at=end_at,
        start_value=None,
        end_value=None,
        change_absolute=None,
        return_percent=None,
        max_up_percent=None,
        max_down_percent=None,
        realized_volatility=None,
        volume_change_percent=None,
        coverage_ratio=0.0,
        direction="missing",
        spike_fade=False,
        dip_recovery=False,
        direction_reversal=False,
        granularity_seconds=86_400,
        quality_grade="D" if source_grade != "UNKNOWN" else "UNKNOWN",
        missing_reason=reason,
        calendar_name=calendar_for_instrument(instrument_key),
        calendar_precision=calendar_precision,
        expected_tradable_bars={"us_cash_close": 1, "next_close": 2, "day_5_close": 6}[
            spec.key
        ],
        experimental=experimental,
        limitations=limitations,
    )


def calculate_session_close_windows(
    bars: list[MarketBarRecord],
    *,
    release_at: datetime,
    source_grade: str,
    instrument_key: str | None,
    session_close_semantics: str,
    limitations: tuple[str, ...] = (),
    specs: tuple[WindowSpec, ...] = SESSION_CLOSE_WINDOW_SPECS,
) -> list[ComputedWindow]:
    """Calculate close horizons from event-linked daily/session-close observations.

    Databento ``ohlcv-1d`` bars are UTC-day aggregates. They may provide an
    explicitly experimental horizon proxy, but never an exchange settlement.
    """

    ordered = sorted(bars, key=lambda item: item.timestamp)
    if not ordered:
        return [
            _missing_session_window(
                release_at=release_at,
                spec=spec,
                instrument_key=instrument_key,
                source_grade=source_grade,
                reason="event_linked_daily_or_session_close_bars_unavailable",
                limitations=(
                    *limitations,
                    "No release-linked daily or provider-declared session-close series was "
                    "available for this long window.",
                ),
                experimental=False,
                calendar_precision="unavailable",
            )
            for spec in specs
        ]
    if session_close_semantics not in {"exchange_session_close", "utc_day"}:
        return [
            _missing_session_window(
                release_at=release_at,
                spec=spec,
                instrument_key=instrument_key,
                source_grade=source_grade,
                reason="daily_boundary_semantics_unverified",
                limitations=(
                    *limitations,
                    "Daily timestamps do not declare exchange session-close or UTC-day "
                    "semantics, so long-window returns were not calculated.",
                ),
                experimental=False,
                calendar_precision="unverified_daily_boundary",
            )
            for spec in specs
        ]

    experimental = session_close_semantics == "utc_day"
    boundary_limitation = (
        "UTC-day OHLC is only an experimental long-horizon proxy; it is not an exchange "
        "settlement or session-close price."
    )
    effective_limitations = (
        (*limitations, boundary_limitation) if experimental else limitations
    )
    if experimental:
        baseline_rows = [bar for bar in ordered if bar.timestamp.date() < release_at.date()]
    else:
        baseline_rows = [bar for bar in ordered if bar.timestamp < release_at]
    baseline = baseline_rows[-1] if baseline_rows else None
    output: list[ComputedWindow] = []
    expected_by_key = {"us_cash_close": 1, "next_close": 2, "day_5_close": 6}
    for spec in specs:
        end_at = resolve_session_window_end(release_at, spec.key, instrument_key)
        if experimental:
            sample = [
                bar
                for bar in ordered
                if release_at.date() <= bar.timestamp.date() <= end_at.date()
            ]
            target_rows = [bar for bar in sample if bar.timestamp.date() == end_at.date()]
        else:
            sample = [bar for bar in ordered if release_at <= bar.timestamp <= end_at]
            target_rows = [bar for bar in sample if bar.timestamp.date() == end_at.date()]
        expected = expected_by_key[spec.key]
        coverage = min(1.0, len(sample) / expected)
        if baseline is None or not sample or not target_rows:
            output.append(
                _missing_session_window(
                    release_at=release_at,
                    spec=spec,
                    instrument_key=instrument_key,
                    source_grade=source_grade,
                    reason="long_window_baseline_or_target_bar_missing",
                    limitations=effective_limitations,
                    experimental=experimental,
                    calendar_precision=(
                        "experimental_utc_day"
                        if experimental
                        else "provider_session_close"
                    ),
                )
            )
            continue
        start_value = baseline.close_value
        end_value = target_rows[-1].close_value
        return_percent = _percent_change(end_value, start_value)
        high_returns = [
            value
            for bar in sample
            if (value := _percent_change(bar.high_value, start_value)) is not None
        ]
        low_returns = [
            value
            for bar in sample
            if (value := _percent_change(bar.low_value, start_value)) is not None
        ]
        path = [start_value, *(bar.close_value for bar in sample)]
        returns = _log_returns(path)
        realized = (
            pstdev(returns) * math.sqrt(len(returns)) * 100
            if len(returns) >= 2
            else 0.0
        )
        grade = _quality_for_coverage(source_grade, coverage)
        if experimental and grade in {"A", "B"}:
            grade = "C"
        missing_reason = (
            "experimental_utc_day_boundary_not_exchange_settlement"
            if experimental
            else "incomplete_session_close_coverage"
            if coverage < 0.8
            else None
        )
        output.append(
            ComputedWindow(
                key=spec.key,
                label=spec.label,
                start_at=release_at,
                end_at=end_at,
                start_value=start_value,
                end_value=end_value,
                change_absolute=end_value - start_value,
                return_percent=return_percent,
                max_up_percent=max(high_returns) if high_returns else None,
                max_down_percent=min(low_returns) if low_returns else None,
                realized_volatility=realized,
                volume_change_percent=None,
                coverage_ratio=coverage,
                direction=_direction(return_percent),
                spike_fade=False,
                dip_recovery=False,
                direction_reversal=False,
                granularity_seconds=86_400,
                quality_grade=grade,
                missing_reason=missing_reason,
                calendar_name=calendar_for_instrument(instrument_key),
                calendar_precision=(
                    "experimental_utc_day" if experimental else "provider_session_close"
                ),
                expected_tradable_bars=expected,
                experimental=experimental,
                limitations=effective_limitations,
            )
        )
    return output


def detect_earliest_reaction(
    instrument_key: str,
    bars: list[MarketBarRecord],
    *,
    release_at: datetime,
    interval_seconds: int,
    confirmation_bars: int = 2,
) -> EarliestReaction | None:
    """Find the first volatility-adjusted move confirmed by consecutive bars."""

    ordered = sorted(bars, key=lambda item: item.timestamp)
    pre = [
        bar for bar in ordered if release_at - timedelta(minutes=60) <= bar.timestamp < release_at
    ]
    post = [
        bar for bar in ordered if release_at <= bar.timestamp <= release_at + timedelta(hours=1)
    ]
    if len(pre) < 10 or len(post) < confirmation_bars:
        return None

    pre_returns = [
        value
        for previous, current in pairwise(pre)
        if (value := _percent_change(current.close_value, previous.close_value)) is not None
    ]
    absolute = [abs(value) for value in pre_returns]
    center = median(absolute) if absolute else 0.0
    mad = median(abs(value - center) for value in absolute) if absolute else 0.0
    volatility = pstdev(pre_returns) if len(pre_returns) >= 2 else 0.0
    threshold = max(
        _MIN_SIGNIFICANCE_PERCENT.get(instrument_key, 0.03),
        center + 4 * mad,
        volatility * 3,
    )
    baseline = pre[-1].close_value
    cumulative = [_percent_change(bar.close_value, baseline) for bar in post]
    for index, value in enumerate(cumulative):
        if value is None or abs(value) < threshold:
            continue
        direction = 1 if value > 0 else -1
        confirmation = cumulative[index : index + confirmation_bars]
        if len(confirmation) < confirmation_bars:
            continue
        if all(
            item is not None and abs(item) >= threshold and (1 if item > 0 else -1) == direction
            for item in confirmation
        ):
            detected = post[index].timestamp
            return EarliestReaction(
                instrument_key=instrument_key,
                detected_at=detected,
                lag_seconds=max(0, int((detected - release_at).total_seconds())),
                move_percent=value,
                direction="up" if direction > 0 else "down",
                threshold_percent=threshold,
                pre_event_volatility=volatility,
                granularity_seconds=interval_seconds,
                confirmation_bars=confirmation_bars,
                limitation=(
                    f"最早观察结果基于{interval_seconds // 60 or 1}分钟bar；"
                    "不能区分同一bar内的先后顺序，也不代表逐笔市场领先。"
                ),
            )
    return None
