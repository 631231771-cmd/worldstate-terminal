"""Small U.S. cash-session calendar for event-relative close windows."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    value = date(year, month, 1)
    value += timedelta(days=(weekday - value.weekday()) % 7)
    return value + timedelta(weeks=occurrence - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    value = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def us_market_holidays(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


def is_us_cash_session(value: date) -> bool:
    return value.weekday() < 5 and value not in us_market_holidays(value.year)


def next_us_cash_session(value: date) -> date:
    candidate = value + timedelta(days=1)
    while not is_us_cash_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def resolve_us_cash_close(release_at: datetime, trading_days_after: int = 0) -> datetime:
    """Return 16:00 New York close while respecting DST and major holidays."""

    local = release_at.astimezone(NEW_YORK)
    session_date = local.date()
    if not is_us_cash_session(session_date) or local.timetz().replace(tzinfo=None) >= time(16):
        session_date = next_us_cash_session(session_date)
    for _ in range(trading_days_after):
        session_date = next_us_cash_session(session_date)
    return datetime.combine(session_date, time(16), tzinfo=NEW_YORK).astimezone(UTC)


def resolve_session_window_end(release_at: datetime, window_key: str) -> datetime:
    if window_key == "us_cash_close":
        return resolve_us_cash_close(release_at)
    if window_key == "next_close":
        return resolve_us_cash_close(release_at, trading_days_after=1)
    if window_key == "day_5_close":
        return resolve_us_cash_close(release_at, trading_days_after=5)
    raise KeyError(f"unknown session window: {window_key}")
