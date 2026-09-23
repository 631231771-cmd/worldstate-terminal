"""Display quotes only: these feeds never create event research manifests."""

import asyncio
import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Literal
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class QuotePoint(BaseModel):
    time: datetime
    value: float


class DisplayQuote(BaseModel):
    key: str
    label: str
    symbol: str
    kind: str
    unit: str
    provider: str
    source_url: str
    price: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_unit: str = "%"
    quoted_at: datetime | None = None
    retrieved_at: datetime | None = None
    delay_minutes: int | None = None
    status: Literal["indicative", "delayed", "stale", "unavailable"] = "unavailable"
    error: str | None = None
    limitation: str
    event_research_eligible: bool = False
    points: list[QuotePoint] = Field(default_factory=list)


SPECS = (
    ("xau_usd", "黄金现货参考", "XAU", "spot_indicative", "USD/盎司", None),
    ("xag_usd", "白银现货参考", "XAG", "spot_indicative", "USD/盎司", None),
    ("gc_quote", "黄金期货", "GC=F", "futures", "USD/盎司", 30),
    ("cl_quote", "WTI 原油期货", "CL=F", "futures", "USD/桶", 30),
    ("es_quote", "标普 500 期货", "ES=F", "futures", "指数点", 10),
    ("nq_quote", "纳指 100 期货", "NQ=F", "futures", "指数点", 10),
    ("btc_quote", "比特币参考", "BTC-USD", "crypto", "USD", 15),
    ("dxy_quote", "美元指数参考", "DX-Y.NYB", "index", "指数点", 15),
    ("us10y_quote", "美债 10Y 收益率", "^TNX", "yield_index", "%", 15),
    ("us5y_quote", "美债 5Y 收益率", "^FVX", "yield_index", "%", 15),
    ("us30y_quote", "美债 30Y 收益率", "^TYX", "yield_index", "%", 15),
    ("zt_quote", "美债 2Y 期货", "ZT=F", "futures", "价格点", 10),
    ("zn_quote", "美债 10Y 期货", "ZN=F", "futures", "价格点", 10),
)


def empty_quotes() -> list[DisplayQuote]:
    return [
        DisplayQuote(
            key=key, label=label, symbol=symbol, kind=kind, unit=unit,
            provider="gold_api" if kind == "spot_indicative" else "yahoo_public",
            source_url=("https://gold-api.com/" if kind == "spot_indicative"
                        else f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/"),
            delay_minutes=delay,
            change_unit="bp" if kind == "yield_index" else "%",
            limitation=(
                "供应商聚合参考报价，非交易所可成交价；未承诺延迟。走势从本次服务采集开始。"
                if kind == "spot_indicative" else
                "公开延迟行情；连续代码不保证具体合约身份，不进入事件研究。"
                if kind == "futures" else
                "公开聚合参考报价，可能延迟；不进入事件研究。"
                if kind in {"crypto", "index"} else
                "Cboe 美债收益率指标，非逐笔现券报价；变化以基点显示。"
            ),
        )
        for key, label, symbol, kind, unit, delay in SPECS
    ]


def number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid numeric quote")
    result = float(value)
    if not isfinite(result):
        raise ValueError("non-finite quote")
    return result


def parse_quote(spec: DisplayQuote, payload: Any, now: datetime) -> DisplayQuote:
    result = spec.model_copy(deep=True)
    if spec.provider == "gold_api":
        if payload.get("symbol") != spec.symbol or payload.get("currency", "USD") != "USD":
            raise ValueError("quote identity mismatch")
        result.price = number(payload["price"])
        result.quoted_at = datetime.fromisoformat(payload["updatedAt"].replace("Z", "+00:00"))
        result.points = [QuotePoint(time=result.quoted_at, value=result.price)]
    else:
        data = payload["chart"]["result"][0]
        meta = data["meta"]
        if meta["symbol"] != spec.symbol:
            raise ValueError("quote identity mismatch")
        result.price = number(meta["regularMarketPrice"])
        result.quoted_at = datetime.fromtimestamp(number(meta["regularMarketTime"]), UTC)
        previous = meta.get("previousClose", meta.get("chartPreviousClose"))
        result.previous_close = number(previous) if previous is not None else None
        if result.previous_close:
            result.change = (
                (result.price - result.previous_close) * 100
                if spec.kind == "yield_index" else
                (result.price / result.previous_close - 1) * 100
            )
        timestamps = data.get("timestamp", [])
        closes = data["indicators"]["quote"][0].get("close", [])
        points = {
            datetime.fromtimestamp(number(t), UTC): number(v)
            for t, v in zip(timestamps, closes, strict=True) if v is not None
        }
        result.points = [QuotePoint(time=t, value=v) for t, v in sorted(points.items())
                         if t <= now][-600:]
    if result.quoted_at.tzinfo is None or (result.quoted_at - now).total_seconds() > 300:
        raise ValueError("quote timestamp is invalid or in the future")
    if result.price <= 0:
        raise ValueError("non-positive quote")
    result.retrieved_at = now
    result.status = "indicative" if spec.provider == "gold_api" else "delayed"
    result.error = None
    return result


def _fetch_quote(spec: DisplayQuote) -> DisplayQuote:
    url = (f"https://api.gold-api.com/price/{spec.symbol}" if spec.provider == "gold_api"
           else f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(spec.symbol, safe='')}"
           "?interval=1m&range=1d")
    # Native urllib also honors the Windows system proxy used by this desktop.
    request = Request(url, headers={"User-Agent": "WorldStateTerminal/0.7"})  # noqa: S310
    with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed HTTPS hosts above
        payload = json.loads(response.read(2_000_000))
    return parse_quote(spec, payload, datetime.now(UTC))


async def fetch_quote(spec: DisplayQuote) -> DisplayQuote:
    return await asyncio.to_thread(_fetch_quote, spec)
