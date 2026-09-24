"""Validate the tiny ATAS chart bridge protocol before it enters display quotes."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_GC_CONTRACT = re.compile(r"GC[FGHJKMNQUVXZ]\d{1,4}\Z")


class LiveMinuteBar(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    start: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def check_bar(self) -> "LiveMinuteBar":
        if self.start.tzinfo is None or self.start.second or self.start.microsecond:
            raise ValueError("minute bar start must be UTC and minute-aligned")
        offset = self.start.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("minute bar start must be UTC")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC range")
        return self


class AtasChartSnapshot(BaseModel):
    """One current chart snapshot, not a historical tick or research dataset."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1]
    symbol: Literal["GC"]
    contract: str | None = None
    source_symbol: str
    exchange: str | None = None
    event_timestamp: datetime
    last_trade_timestamp: datetime | None = None
    last_trade: float | None = Field(default=None, gt=0)
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    last_trade_volume: float | None = Field(default=None, ge=0)
    bar_1m: LiveMinuteBar | None = None

    @model_validator(mode="after")
    def check_identity(self) -> "AtasChartSnapshot":
        if self.contract is None:
            if self.source_symbol != "GC":
                raise ValueError("unverified GC chart must retain its GC root")
        elif not _GC_CONTRACT.fullmatch(self.contract):
            raise ValueError("a specific GC chart contract is required")
        elif self.source_symbol not in {self.contract, f"#{self.contract}"}:
            raise ValueError("ATAS source symbol does not resolve to GC contract")
        if self.event_timestamp.tzinfo is None or self.event_timestamp.utcoffset() is None:
            raise ValueError("event timestamp must be UTC")
        event_offset = self.event_timestamp.utcoffset()
        if event_offset is None or event_offset.total_seconds() != 0:
            raise ValueError("event timestamp must be UTC")
        if self.last_trade is not None:
            if self.last_trade_timestamp is None or self.last_trade_timestamp.tzinfo is None:
                raise ValueError("last trade timestamp must be UTC")
            if self.last_trade_timestamp.utcoffset() is None:
                raise ValueError("last trade timestamp must be UTC")
            trade_offset = self.last_trade_timestamp.utcoffset()
            if trade_offset is None or trade_offset.total_seconds() != 0:
                raise ValueError("last trade timestamp must be UTC")
            if self.last_trade_timestamp > self.event_timestamp:
                raise ValueError("last trade occurs after event")
        if (self.best_bid is not None and self.best_ask is not None
                and self.best_bid > self.best_ask):
            raise ValueError("crossed bid/ask")
        if self.last_trade is None and self.best_bid is None and self.best_ask is None:
            raise ValueError("snapshot has no market value")
        if self.bar_1m and self.bar_1m.start > self.event_timestamp:
            raise ValueError("minute bar starts after event")
        return self
