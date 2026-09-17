"""Bounded, shared display cache; no writes to the research database."""

import asyncio
from datetime import UTC, datetime
from time import monotonic

from pydantic import BaseModel

from worldstate.provider_kit.public_quotes import DisplayQuote, empty_quotes, fetch_quote


class QuotesResponse(BaseModel):
    as_of: datetime
    refresh_seconds: int = 60
    items: list[DisplayQuote]


class QuoteService:
    def __init__(self) -> None:
        self.items = empty_quotes()
        self.next_refresh = 0.0
        self.lock = asyncio.Lock()

    async def read(self) -> QuotesResponse:
        async with self.lock:
            if monotonic() >= self.next_refresh:
                results = await asyncio.gather(
                    *(fetch_quote(item) for item in self.items), return_exceptions=True,
                )
                for index, result in enumerate(results):
                    old = self.items[index]
                    if isinstance(result, BaseException):
                        old.error = (
                            "报价源暂时不可用，保留最后报价" if old.price else "报价源暂时不可用"
                        )
                        old.status = "stale" if old.price else "unavailable"
                        continue
                    if old.quoted_at and result.quoted_at and result.quoted_at < old.quoted_at:
                        old.error = "来源返回了较旧报价，保留最后报价"
                        old.status = "stale"
                        continue
                    if result.provider == "gold_api":
                        points = {p.time: p for p in [*old.points, *result.points]}
                        result.points = sorted(points.values(), key=lambda p: p.time)[-600:]
                    self.items[index] = result
                self.next_refresh = monotonic() + 60
            now = datetime.now(UTC)
            items = [item.model_copy(deep=True) for item in self.items]
            for item in items:
                if item.quoted_at and (now - item.quoted_at).total_seconds() > (
                    (item.delay_minutes or 0) * 60 + 300
                ):
                    item.status = "stale"
            return QuotesResponse(as_of=now, items=items)
