"""Deterministic, visibly labelled market fixtures for workflow tests."""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta
from decimal import Decimal

from worldstate.provider_kit.models import MarketBarRecord

_BASE = {
    "gold_gc": 2160.0,
    "silver_si": 24.5,
    "wti_cl": 80.0,
    "sp500_es": 5200.0,
    "nasdaq_nq": 18200.0,
    "ust2y_zt": 102.5,
    "ust10y_zn": 111.0,
    "dollar_dxy": 104.0,
    "eurusd": 1.085,
    "usdjpy": 150.0,
    "vix": 14.0,
}


def _stage_path(minute_after: float, shock_percent: float) -> float:
    if minute_after < 0:
        return 0.0
    if minute_after <= 5:
        return shock_percent * ((minute_after + 1) / 6)
    if minute_after <= 30:
        return shock_percent * (1 - 0.25 * ((minute_after - 5) / 25))
    return shock_percent * 0.75


def generate_scenario_bars(
    *,
    scenario_key: str,
    instrument_key: str,
    symbol: str,
    contract_code: str,
    stages: list[tuple[datetime, float]],
) -> list[MarketBarRecord]:
    """Generate illustrative OHLCV around one or more release stages."""

    if not stages:
        return []
    start = min(item[0] for item in stages) - timedelta(minutes=60)
    end = max(item[0] for item in stages) + timedelta(minutes=240)
    total_minutes = int((end - start).total_seconds() / 60)
    base = _BASE[instrument_key]
    digest = hashlib.sha256(f"{scenario_key}:{instrument_key}".encode()).digest()
    randomizer = random.Random(int.from_bytes(digest[:8]))
    noise = 0.006 if base > 100 else 0.012
    previous = base
    output: list[MarketBarRecord] = []
    for index in range(total_minutes + 1):
        timestamp = start + timedelta(minutes=index)
        stage_shock = sum(
            _stage_path((timestamp - anchor).total_seconds() / 60, shock)
            for anchor, shock in stages
        )
        wave = math.sin((index + digest[8]) / 11) * noise * 0.4
        random_noise = randomizer.gauss(0, noise * 0.22)
        close = base * (1 + (stage_shock + wave + random_noise) / 100)
        range_percent = noise * (
            2.2
            if any(0 <= (timestamp - anchor).total_seconds() <= 900 for anchor, _ in stages)
            else 0.8
        )
        high = max(previous, close) * (1 + range_percent / 100)
        low = min(previous, close) * (1 - range_percent / 100)
        volume = 950 + abs(randomizer.gauss(0, 80))
        if any(0 <= (timestamp - anchor).total_seconds() <= 900 for anchor, _ in stages):
            volume *= 2.8
        output.append(
            MarketBarRecord(
                instrument_key=instrument_key,
                timestamp=timestamp,
                interval_seconds=60,
                open_value=Decimal(f"{previous:.8f}"),
                high_value=Decimal(f"{high:.8f}"),
                low_value=Decimal(f"{low:.8f}"),
                close_value=Decimal(f"{close:.8f}"),
                volume=Decimal(f"{volume:.2f}"),
                source_symbol=f"FIXTURE:{symbol}",
                contract_code=contract_code,
                metadata={
                    "fixture": True,
                    "fixture_method": "multi-stage-reaction-v1",
                    "scenario_key": scenario_key,
                },
            )
        )
        previous = close
    return output
