"""Optional boundary for Macrosynergy analytics.

Database records and API responses never expose Macrosynergy's internal
QuantamentalDataFrame type.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from datetime import date
from importlib import import_module


class MacrosynergyAdapter:
    """Convert WorldState rows to and from the optional analysis package."""

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("macrosynergy") is not None

    def status(self) -> dict[str, object]:
        return {
            "available": self.available,
            "mode": "optional_dependency",
            "license": "BSD-3-Clause",
            "boundary": "worldstate_adapter_v1",
        }

    def to_quantamental_records(
        self,
        rows: Sequence[tuple[str, date, float]],
        *,
        category: str,
    ) -> list[dict[str, object]]:
        """Return package-compatible records without importing pandas."""

        return [
            {
                "cid": instrument_key.upper(),
                "xcat": category,
                "real_date": observed_on.isoformat(),
                "value": value,
            }
            for instrument_key, observed_on, value in rows
        ]

    def historical_volatility(
        self,
        rows: Sequence[tuple[str, date, float]],
        *,
        lookback: int = 21,
    ) -> dict[str, float]:
        """Cross-check volatility when Macrosynergy is installed."""

        if not self.available:
            raise RuntimeError("Macrosynergy is not installed")
        if len(rows) < lookback:
            raise ValueError(f"at least {lookback} rows are required")

        pd = import_module("pandas")
        historic_vol = import_module("macrosynergy.panel.historic_vol").historic_vol

        frame = pd.DataFrame(self.to_quantamental_records(rows, category="EVENT_RET"))
        result = historic_vol(
            frame,
            xcat="EVENT_RET",
            lback_periods=lookback,
            est_freq="D",
            postfix="ASD",
        )
        latest = result.sort_values("real_date").groupby("cid").tail(1)
        return {str(row["cid"]).lower(): float(row["value"]) for _index, row in latest.iterrows()}
