"""Normalize and validate user-supplied event-minute bars before persistence."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import MacroRelease, MarketInstrument, ReleaseStage

DEFAULT_COLUMN_MAPPING: dict[str, str] = {
    "timestamp": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "contract_code": "contract_code",
    "source_symbol": "source_symbol",
}

EVENT_ASSETS: tuple[dict[str, str], ...] = (
    {"key": "gold_gc", "label": "黄金 / GC", "unit": "%"},
    {"key": "sp500_es", "label": "标普 500 / ES", "unit": "%"},
    {"key": "nasdaq_nq", "label": "纳斯达克 100 / NQ", "unit": "%"},
    {"key": "ust2y_zt", "label": "美国 2 年期国债 / ZT", "unit": "%"},
    {"key": "ust10y_zn", "label": "美国 10 年期国债 / ZN", "unit": "%"},
    {"key": "dollar_dxy", "label": "美元指数 / DX", "unit": "%"},
    {"key": "wti_cl", "label": "WTI 原油 / CL", "unit": "%"},
    {"key": "vix", "label": "VIX / VX", "unit": "%"},
)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_timestamp(value: str, timezone_name: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {timezone_name}") from exc
    return parsed.astimezone(UTC)


def _mapped(row: dict[str, str | None], mapping: dict[str, str], key: str) -> str:
    source = mapping.get(key, key)
    return str(row.get(source) or "").strip()


def normalize_event_minute_csv(
    csv_text: str,
    *,
    instrument_key: str,
    timezone_name: str = "UTC",
    column_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a normalized UTC OHLCV CSV plus transparent validation facts."""

    mapping = {**DEFAULT_COLUMN_MAPPING, **(column_mapping or {})}
    reader = csv.DictReader(io.StringIO(csv_text))
    columns = set(reader.fieldnames or [])
    required = {mapping[key] for key in ("timestamp", "open", "high", "low", "close")}
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"CSV is missing mapped columns: {', '.join(missing)}")

    parsed_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[datetime] = set()
    duplicate_count = 0
    input_timestamps: list[datetime] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            timestamp = _parse_timestamp(_mapped(row, mapping, "timestamp"), timezone_name)
            open_value = Decimal(_mapped(row, mapping, "open"))
            high_value = Decimal(_mapped(row, mapping, "high"))
            low_value = Decimal(_mapped(row, mapping, "low"))
            close_value = Decimal(_mapped(row, mapping, "close"))
            if high_value < max(open_value, close_value) or low_value > min(
                open_value, close_value
            ):
                raise ValueError("OHLC range is inconsistent")
            volume_text = _mapped(row, mapping, "volume")
            volume = Decimal(volume_text) if volume_text else None
            if timestamp in seen:
                duplicate_count += 1
                warnings.append(f"row {row_number}: duplicate timestamp; last row wins")
                parsed_rows = [item for item in parsed_rows if item["timestamp"] != timestamp]
            seen.add(timestamp)
            input_timestamps.append(timestamp)
            parsed_rows.append(
                {
                    "timestamp": timestamp,
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                    "volume": volume,
                    "contract_code": _mapped(row, mapping, "contract_code"),
                    "source_symbol": _mapped(row, mapping, "source_symbol"),
                }
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            errors.append(f"row {row_number}: {exc}")

    if not parsed_rows:
        raise ValueError("CSV contains no valid market bars")
    sorted_input = input_timestamps == sorted(input_timestamps)
    if not sorted_input:
        warnings.append("input timestamps were not sorted; preview is normalized to UTC order")
    parsed_rows.sort(key=lambda item: item["timestamp"])

    gaps = [
        int((right["timestamp"] - left["timestamp"]).total_seconds())
        for left, right in pairwise(parsed_rows)
    ]
    one_minute_intervals = sum(value == 60 for value in gaps)
    interval_ratio = one_minute_intervals / len(gaps) if gaps else 0.0
    missing_bar_count = sum(max(0, value // 60 - 1) for value in gaps if value > 60)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "timestamp",
            "instrument_key",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "interval_seconds",
            "source_symbol",
            "contract_code",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for item in parsed_rows:
        writer.writerow(
            {
                "timestamp": item["timestamp"].isoformat().replace("+00:00", "Z"),
                "instrument_key": instrument_key,
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item["volume"] if item["volume"] is not None else "",
                "interval_seconds": 60,
                "source_symbol": item["source_symbol"],
                "contract_code": item["contract_code"],
            }
        )
    return {
        "normalized_csv": output.getvalue(),
        "rows": parsed_rows,
        "row_count": len(parsed_rows),
        "first_timestamp": parsed_rows[0]["timestamp"],
        "last_timestamp": parsed_rows[-1]["timestamp"],
        "duplicate_count": duplicate_count,
        "missing_bar_count": missing_bar_count,
        "one_minute_interval_ratio": interval_ratio,
        "sorted_input": sorted_input,
        "errors": errors,
        "warnings": warnings,
    }


def evaluate_event_intraday_eligibility(
    normalized: dict[str, Any],
    *,
    t0: datetime,
    data_mode: str,
    is_fixture: bool,
    verified: bool,
) -> dict[str, Any]:
    """Classify event-minute evidence without treating successful storage as eligibility."""

    rows = normalized["rows"]
    timestamps = [item["timestamp"] for item in rows]
    anchor = _aware(t0)
    nearest_seconds = min(abs((item - anchor).total_seconds()) for item in timestamps)
    pre_minutes = max(0, int((anchor - min(timestamps)).total_seconds() // 60))
    post_minutes = max(0, int((max(timestamps) - anchor).total_seconds() // 60))
    reasons: list[str] = []
    limitations: list[str] = []
    hard_failure = False

    if data_mode not in {"observed", "fixture"}:
        reasons.append("未知的数据模式不能进入事件研究")
        hard_failure = True
    if data_mode == "observed" and is_fixture:
        reasons.append("Fixture 数据不能进入 observed 事件研究")
        hard_failure = True
    if data_mode == "fixture" and not is_fixture:
        reasons.append("Observed 数据不能混入 fixture 演示研究")
        hard_failure = True
    if nearest_seconds > 60:
        reasons.append("T0 附近缺少一分钟行情")
        hard_failure = True
    if normalized["one_minute_interval_ratio"] < 0.95:
        reasons.append("数据并非稳定的一分钟频率")
        hard_failure = True
    if normalized["duplicate_count"]:
        limitations.append(f"发现并去重 {normalized['duplicate_count']} 个重复时间戳")
    if normalized["missing_bar_count"]:
        limitations.append(f"事件窗口内估计缺少 {normalized['missing_bar_count']} 根 bar")
    if normalized["errors"]:
        limitations.append(f"有 {len(normalized['errors'])} 行无法解析")
    if pre_minutes < 15:
        limitations.append("事件前覆盖不足 15 分钟")
    if post_minutes < 60:
        limitations.append("事件后覆盖不足 60 分钟")
    if not verified:
        limitations.append("数据由用户手工导入且尚未人工核验")

    if hard_failure:
        status = "ineligible"
    elif pre_minutes >= 15 and post_minutes >= 60 and not normalized["missing_bar_count"]:
        status = "eligible"
    else:
        status = "partial"
    if status == "eligible":
        reasons.append("T0、频率及最小事件窗口覆盖通过")
    elif status == "partial":
        reasons.append("T0 可用，但覆盖或完整性不足，暂不进入 Event Engine")
    return {
        "status": status,
        "eligible": status == "eligible",
        "reasons": reasons,
        "limitations": limitations,
        "bar_count": normalized["row_count"],
        "first_timestamp": normalized["first_timestamp"].isoformat(),
        "last_timestamp": normalized["last_timestamp"].isoformat(),
        "nearest_t0_seconds": int(nearest_seconds),
        "pre_event_minutes": pre_minutes,
        "post_event_minutes": post_minutes,
        "missing_bar_count": normalized["missing_bar_count"],
        "duplicate_count": normalized["duplicate_count"],
        "one_minute_interval_ratio": round(normalized["one_minute_interval_ratio"], 6),
        "granularity_seconds": 60,
        "data_mode": data_mode,
        "is_fixture": is_fixture,
        "manual": True,
        "verified": verified,
    }


async def preview_event_minute_csv(
    engine: AsyncEngine,
    *,
    release_id: str,
    instrument_key: str,
    csv_text: str,
    timezone_name: str,
    column_mapping: dict[str, str] | None,
    verified: bool,
    is_fixture: bool,
) -> dict[str, Any]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError as exc:
            raise LookupError("macro release not found") from exc
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            raise LookupError("macro release not found")
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == instrument_key)
        )
        if instrument is None:
            raise LookupError("market instrument not found")
        stages = list(
            (
                await session.scalars(
                    select(ReleaseStage)
                    .where(ReleaseStage.macro_release_id == release.id)
                    .order_by(ReleaseStage.sequence)
                )
            ).all()
        )
        t0 = _aware(
            (stages[0].released_at or stages[0].scheduled_at)
            if stages
            else (release.released_at or release.scheduled_at)
        )
    normalized = normalize_event_minute_csv(
        csv_text,
        instrument_key=instrument_key,
        timezone_name=timezone_name,
        column_mapping=column_mapping,
    )
    eligibility = evaluate_event_intraday_eligibility(
        normalized,
        t0=t0,
        data_mode=release.data_mode,
        is_fixture=is_fixture,
        verified=verified,
    )
    preview = [
        {
            "timestamp": item["timestamp"].isoformat(),
            "open": str(item["open"]),
            "high": str(item["high"]),
            "low": str(item["low"]),
            "close": str(item["close"]),
            "volume": str(item["volume"]) if item["volume"] is not None else None,
        }
        for item in normalized["rows"][:20]
    ]
    return {
        "release_id": release_id,
        "instrument": {
            "key": instrument.canonical_key,
            "label": instrument.title,
            "symbol": instrument.symbol,
            "is_proxy": instrument.is_proxy,
            "proxy_for": instrument.proxy_for,
        },
        "t0": t0.isoformat(),
        "timezone": timezone_name,
        "eligibility": eligibility,
        "preview": preview,
        "parse_errors": normalized["errors"][:20],
        "warnings": normalized["warnings"][:20],
        "normalized_csv": normalized["normalized_csv"],
    }


async def release_event_assets(engine: AsyncEngine) -> list[dict[str, Any]]:
    """Return only supported event instruments that really exist in the catalog."""

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        keys = [item["key"] for item in EVENT_ASSETS]
        rows = list(
            (
                await session.scalars(
                    select(MarketInstrument).where(MarketInstrument.canonical_key.in_(keys))
                )
            ).all()
        )
    by_key = {item.canonical_key: item for item in rows}
    return [
        {
            **candidate,
            "symbol": by_key[candidate["key"]].symbol,
            "is_proxy": by_key[candidate["key"]].is_proxy,
            "proxy_for": by_key[candidate["key"]].proxy_for,
        }
        for candidate in EVENT_ASSETS
        if candidate["key"] in by_key
    ]


__all__ = [
    "DEFAULT_COLUMN_MAPPING",
    "EVENT_ASSETS",
    "evaluate_event_intraday_eligibility",
    "normalize_event_minute_csv",
    "preview_event_minute_csv",
    "release_event_assets",
]
