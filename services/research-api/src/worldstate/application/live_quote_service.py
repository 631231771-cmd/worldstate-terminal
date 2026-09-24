"""Ephemeral, opt-in GC display feed. No research persistence or market import."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from worldstate.provider_kit.atas_local import AtasChartSnapshot
from worldstate.provider_kit.public_quotes import DisplayQuote, QuotePoint


class LiveGcResponse(BaseModel):
    enabled: bool
    connected: bool
    last_seen_at: datetime | None = None
    quote: DisplayQuote | None = None


class LiveQuoteService:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._connection: str | None = None
        self._last_seen_at: datetime | None = None
        self._quote: DisplayQuote | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> str:
        if not self.enabled:
            raise ValueError("ATAS bridge is disabled")
        async with self._lock:
            if self._connection is not None:
                raise ValueError("a chart bridge is already connected")
            self._connection = uuid4().hex
            return self._connection

    async def disconnect(self, connection: str) -> None:
        async with self._lock:
            if self._connection == connection:
                self._connection = None

    async def ingest(self, connection: str, snapshot: AtasChartSnapshot) -> None:
        now = datetime.now(UTC)
        event_at = snapshot.event_timestamp.astimezone(UTC)
        # Refuse replayed or future data. This feed is operational UI only.
        if not -5 <= (now - event_at).total_seconds() <= 30:
            raise ValueError("ATAS chart event is not current")
        async with self._lock:
            if self._connection != connection:
                raise ValueError("ATAS bridge connection is no longer active")
            previous = self._quote
            if previous and previous.symbol != snapshot.contract:
                previous = None  # Do not join two contracts into one chart.
            points = list(previous.points) if previous else []
            if snapshot.bar_1m:
                point = QuotePoint(time=snapshot.bar_1m.start, value=snapshot.bar_1m.close)
                points = [p for p in points if p.time != point.time]
                points.append(point)
                points = sorted(points, key=lambda p: p.time)[-120:]
            price = snapshot.last_trade or (previous.price if previous else None)
            trade_at = snapshot.last_trade_timestamp or (previous.quoted_at if previous else None)
            self._quote = DisplayQuote(
                key="gc_quote", label="黄金期货", symbol=snapshot.contract,
                kind="futures", unit="USD/盎司", provider="atas_local_bridge", source_url="",
                price=price, quoted_at=trade_at, retrieved_at=now, delay_minutes=0,
                status="live", error=None,
                limitation=("ATAS 当前 GC 图表的本机展示流；仅供观察，不保存至事件研究。"
                            "试用数据授权仍需用户确认。"),
                event_research_eligible=False, points=points,
                contract_code=snapshot.contract, exchange=snapshot.exchange,
                source_symbol=snapshot.source_symbol,
                best_bid=snapshot.best_bid, best_ask=snapshot.best_ask,
                last_trade_volume=snapshot.last_trade_volume,
                bar_1m=snapshot.bar_1m,
                event_at=event_at,
                received_at=now,
            )
            self._last_seen_at = now

    async def read(self) -> LiveGcResponse:
        async with self._lock:
            now = datetime.now(UTC)
            connected = self._connection is not None
            quote = self._quote.model_copy(deep=True) if self._quote else None
            if quote and (
                not connected or self._last_seen_at is None
                or now - self._last_seen_at > timedelta(seconds=5)
                or quote.quoted_at is None
                or now - quote.quoted_at > timedelta(seconds=30)
            ):
                quote.status = "stale"
                quote.error = "ATAS 本机行情已断开或未更新"
            return LiveGcResponse(
                enabled=self.enabled, connected=connected,
                last_seen_at=self._last_seen_at, quote=quote,
            )
