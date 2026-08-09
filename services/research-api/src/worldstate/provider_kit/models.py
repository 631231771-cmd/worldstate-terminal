"""WorldState-owned OHLCV contracts."""

from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from worldstate.data_quality import DataQuality


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketInstrumentRef(ImmutableModel):
    canonical_key: str
    symbol: str
    title: str
    exchange: str | None
    quote_unit: str
    is_proxy: bool = False
    proxy_for: str | None = None


class BarQuery(ImmutableModel):
    instrument: MarketInstrumentRef
    start: AwareDatetime
    end: AwareDatetime
    interval_seconds: int = Field(default=60, ge=1)


class MarketBarRecord(ImmutableModel):
    instrument_key: str
    timestamp: AwareDatetime
    interval_seconds: int = Field(ge=1)
    open_value: Decimal
    high_value: Decimal
    low_value: Decimal
    close_value: Decimal
    volume: Decimal | None = None
    source_symbol: str
    contract_code: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "MarketBarRecord":
        if self.high_value < max(self.open_value, self.close_value, self.low_value):
            raise ValueError("high must be at least open, close, and low")
        if self.low_value > min(self.open_value, self.close_value, self.high_value):
            raise ValueError("low must be at most open, close, and high")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")
        return self


class MarketBarBatch(ImmutableModel):
    provider_key: str
    instrument: MarketInstrumentRef
    bars: list[MarketBarRecord]
    quality: DataQuality
    fetched_at: AwareDatetime
    warnings: list[str] = Field(default_factory=list)

    @property
    def start(self) -> datetime | None:
        return self.bars[0].timestamp if self.bars else None

    @property
    def end(self) -> datetime | None:
        return self.bars[-1].timestamp if self.bars else None
