"""Declared lite calendars for cash, CME-style futures, and 24x5 FX windows.

This is deliberately an exchange-session-lite calendar, not a licensed exchange
calendar.  It handles the named closures/maintenance interval and marks the
remaining holiday schedule as limited in API metadata.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
CME_KEYS = {"gold_gc", "silver_si", "wti_cl", "sp500_es", "nasdaq_nq", "ust2y_zt", "ust10y_zn"}
FX_KEYS = {"eurusd", "usdjpy", "dollar_dxy"}


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    value = date(year, month, 1) + timedelta(days=(weekday - date(year, month, 1).weekday()) % 7)
    return value + timedelta(weeks=occurrence - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    value = next_month - timedelta(days=1)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def _observed(value: date) -> date:
    return (
        value - timedelta(days=1)
        if value.weekday() == 5
        else value + timedelta(days=1)
        if value.weekday() == 6
        else value
    )


def _easter(year: int) -> date:
    # Meeus/Jones/Butcher Gregorian computus; used only for Good Friday.
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * offset) // 451
    return date(
        year,
        (h + offset - 7 * m + 114) // 31,
        (h + offset - 7 * m + 114) % 31 + 1,
    )


def us_market_holidays(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


def early_close(value: date) -> time | None:
    thanksgiving = _nth_weekday(value.year, 11, 3, 4)
    if value == thanksgiving + timedelta(days=1):
        return time(13)
    if value.month == 7 and value.day == 3 and value.weekday() < 5:
        return time(13)
    if value.month == 12 and value.day == 24 and value.weekday() < 5:
        return time(13)
    return None


def is_us_cash_session(value: date) -> bool:
    return value.weekday() < 5 and value not in us_market_holidays(value.year)


def next_us_cash_session(value: date) -> date:
    candidate = value + timedelta(days=1)
    while not is_us_cash_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def resolve_us_cash_close(release_at: datetime, trading_days_after: int = 0) -> datetime:
    local, session_date = release_at.astimezone(NEW_YORK), release_at.astimezone(NEW_YORK).date()
    close = early_close(session_date) or time(16)
    if not is_us_cash_session(session_date) or local.timetz().replace(tzinfo=None) >= close:
        session_date = next_us_cash_session(session_date)
    for _ in range(trading_days_after):
        session_date = next_us_cash_session(session_date)
    return datetime.combine(
        session_date, early_close(session_date) or time(16), tzinfo=NEW_YORK
    ).astimezone(UTC)


def calendar_for_instrument(instrument_key: str | None) -> str:
    if instrument_key in CME_KEYS:
        return "cme_comex_nymex_lite"
    if instrument_key in FX_KEYS:
        return "fx_24x5_lite"
    return "us_cash_lite"


def is_tradable_minute(moment: datetime, instrument_key: str | None) -> bool:
    local = moment.astimezone(NEW_YORK)
    calendar = calendar_for_instrument(instrument_key)
    if calendar == "us_cash_lite":
        close = early_close(local.date()) or time(16)
        return (
            is_us_cash_session(local.date())
            and time(9, 30) <= local.time().replace(tzinfo=None) < close
        )
    if calendar == "fx_24x5_lite":
        # Retail FX convention: Sunday 17:00 ET through Friday 17:00 ET.
        return not (
            local.weekday() == 5
            or (local.weekday() == 6 and local.time().replace(tzinfo=None) < time(17))
            or (local.weekday() == 4 and local.time().replace(tzinfo=None) >= time(17))
        )
    # CME/COMEX/NYMEX: daily maintenance 17:00-18:00 ET, with Good Friday closure.
    if local.weekday() == 5:
        return False
    if local.weekday() == 6:
        return local.time().replace(tzinfo=None) >= time(18)
    if local.date() in us_market_holidays(local.year):
        return False
    if local.weekday() == 4 and local.time().replace(tzinfo=None) >= time(17):
        return False
    return not (time(17) <= local.time().replace(tzinfo=None) < time(18))


def _is_session_date(value: date, instrument_key: str | None) -> bool:
    calendar = calendar_for_instrument(instrument_key)
    if calendar == "fx_24x5_lite":
        return value.weekday() < 5
    return is_us_cash_session(value)


def _next_session_date(value: date, instrument_key: str | None) -> date:
    candidate = value + timedelta(days=1)
    while not _is_session_date(candidate, instrument_key):
        candidate += timedelta(days=1)
    return candidate


def _reference_close(value: date, instrument_key: str | None) -> time:
    calendar = calendar_for_instrument(instrument_key)
    if calendar == "us_cash_lite":
        return early_close(value) or time(16)
    # A declared research-window boundary, not an exchange settlement timestamp.
    return early_close(value) or time(17)


def resolve_instrument_close(
    release_at: datetime,
    instrument_key: str | None,
    trading_days_after: int = 0,
) -> datetime:
    local = release_at.astimezone(NEW_YORK)
    session_date = local.date()
    close = _reference_close(session_date, instrument_key)
    if (
        not _is_session_date(session_date, instrument_key)
        or local.time().replace(tzinfo=None) >= close
    ):
        session_date = _next_session_date(session_date, instrument_key)
    for _ in range(trading_days_after):
        session_date = _next_session_date(session_date, instrument_key)
    return datetime.combine(
        session_date,
        _reference_close(session_date, instrument_key),
        tzinfo=NEW_YORK,
    ).astimezone(UTC)


def expected_tradable_bars(
    start_at: datetime, end_at: datetime, interval_seconds: int, instrument_key: str | None
) -> int:
    cursor, count = start_at, 0
    step = timedelta(seconds=interval_seconds)
    while cursor < end_at:
        if is_tradable_minute(cursor, instrument_key):
            count += 1
        cursor += step
    return max(1, count)


def resolve_session_window_end(
    release_at: datetime, window_key: str, instrument_key: str | None = None
) -> datetime:
    if window_key == "us_cash_close":
        return resolve_instrument_close(release_at, instrument_key)
    if window_key == "next_close":
        return resolve_instrument_close(release_at, instrument_key, trading_days_after=1)
    if window_key == "day_5_close":
        return resolve_instrument_close(release_at, instrument_key, trading_days_after=5)
    raise KeyError(f"unknown session window: {window_key}")
