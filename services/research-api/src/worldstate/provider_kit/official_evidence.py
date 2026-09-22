"""Free official exports, normalized before entering research application logic.

All endpoints are current-version history. Observation dates are NOT publication
timestamps or historical vintages. Acquisition time is the availability boundary.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from defusedxml.ElementTree import fromstring

from worldstate.provider_kit.contracts import ProviderRetryPolicy
from worldstate.provider_kit.transport import HttpProviderTransport

USER_AGENT = "WorldStateTerminal/0.7 (+https://github.com/631231771-cmd/worldstate-terminal)"
COT_MARKETS = {
    "088691": "gold",
    "067651": "oil",
    "042601": "ust2y",
    "043602": "ust10y",
    "13874A": "sp500",
    "099741": "eur",
}


@dataclass(frozen=True)
class EvidencePoint:
    key: str
    title: str
    period: date
    value: Decimal
    unit: str
    frequency: str


def number(value: object) -> Decimal:
    result = Decimal(str(value).replace(",", "").strip())
    if not result.is_finite():
        raise ValueError("nonfinite official observation")
    return result


def parse_eia(content: bytes, table: str) -> list[EvidencePoint]:
    rows = list(csv.reader(io.StringIO(content.decode("cp1252"))))
    output: list[EvidencePoint] = []
    dates: list[date] = []
    offset = 0
    for row in rows:
        if row and row[0] == "STUB_1":
            offset = 2 if len(row) > 1 and row[1] == "STUB_2" else 1
            dates = [datetime.strptime(v, "%m/%d/%y").date() for v in row[offset : offset + 2]]
            continue
        if not dates or len(row) < offset + 2:
            continue
        label = re.sub(r"^\(\d+\)\s*", "", row[offset - 1]).strip()
        group = row[0].strip() if offset == 2 else "stocks"
        mapping = {
            ("stocks", "Commercial (Excluding SPR)"): (
                "crude_stocks",
                "美国商业原油库存（不含 SPR）",
                "million_barrels",
            ),
            ("Crude Oil Supply", "Domestic Production"): (
                "production",
                "美国原油产量",
                "thousand_barrels_per_day",
            ),
            ("Crude Oil Supply", "Imports"): (
                "imports",
                "美国原油进口",
                "thousand_barrels_per_day",
            ),
            ("Crude Oil Supply", "Exports"): (
                "exports",
                "美国原油出口",
                "thousand_barrels_per_day",
            ),
            ("Products Supplied", "Total"): (
                "products_supplied",
                "美国石油产品供应量（需求代理）",
                "thousand_barrels_per_day",
            ),
            ("Refiner Inputs and Utilization", "Percent Utilization"): (
                "refinery_utilization",
                "美国炼厂开工率",
                "percent",
            ),
        }
        match = mapping.get((group, label))
        if match is None or (table == "table9" and match[0] != "refinery_utilization"):
            continue
        key, title, unit = match
        for period, raw in zip(dates, row[offset : offset + 2], strict=True):
            output.append(EvidencePoint(f"eia.{key}", title, period, number(raw), unit, "weekly"))
    if not output:
        raise ValueError(f"EIA {table} has no recognized rows; schema may have changed")
    return output


def parse_treasury(content: bytes, real: bool) -> list[EvidencePoint]:
    root = fromstring(content)
    output: list[EvidencePoint] = []
    for properties in root.iter():
        if properties.tag.rsplit("}", 1)[-1] != "properties":
            continue
        fields = {node.tag.rsplit("}", 1)[-1]: node.text for node in properties}
        period = date.fromisoformat(str(fields["NEW_DATE"])[:10])
        for tenor in (5, 7, 10, 20, 30) if real else (2, 5, 10, 30):
            raw = fields.get(f"{'TC' if real else 'BC'}_{tenor}YEAR")
            if raw is not None:
                key = f"treasury.{'real' if real else 'nominal'}_{tenor}y"
                output.append(
                    EvidencePoint(
                        key,
                        f"美国 {tenor} 年{'实际' if real else '名义'}收益率",
                        period,
                        number(raw),
                        "percent",
                        "daily",
                    )
                )
    if not output:
        raise ValueError("Treasury feed has no recognized curve observations")
    return output


def parse_nyfed(content: bytes, dataset: str) -> list[EvidencePoint]:
    payload = json.loads(content)
    output: list[EvidencePoint] = []
    if dataset == "sofr":
        for row in payload["refRates"]:
            period = date.fromisoformat(row["effectiveDate"])
            for field, key, title, unit in (
                ("percentRate", "sofr", "SOFR 担保隔夜融资利率", "percent"),
                ("volumeInBillions", "sofr_volume", "SOFR 成交规模", "billion_usd"),
            ):
                output.append(
                    EvidencePoint(f"nyfed.{key}", title, period, number(row[field]), unit, "daily")
                )
    else:
        totals: dict[date, Decimal] = {}
        for row in payload["repo"]["operations"]:
            if row.get("term") != "Overnight" or row.get("operationType") != "Reverse Repo":
                continue
            period = date.fromisoformat(row["operationDate"])
            totals[period] = totals.get(period, Decimal(0)) + number(row["totalAmtAccepted"])
        output = [
            EvidencePoint(
                "nyfed.on_rrp",
                "纽约联储隔夜逆回购接受量",
                period,
                value / Decimal(10**9),
                "billion_usd",
                "daily",
            )
            for period, value in totals.items()
        ]
    if not output:
        raise ValueError("NY Fed export has no recognized observations")
    return output


def parse_cftc(content: bytes) -> list[EvidencePoint]:
    output: list[EvidencePoint] = []
    rows: list[dict[str, Any]] = json.loads(content)
    if len(rows) >= 5000:
        raise ValueError("CFTC response reached row cap; refuse truncated sample")
    for row in rows:
        code = str(row["cftc_contract_market_code"]).strip()
        if code not in COT_MARKETS or row.get("futonly_or_combined") != "FutOnly":
            continue
        asset = COT_MARKETS[code]
        period = date.fromisoformat(row["report_date_as_yyyy_mm_dd"][:10])
        net = number(row["noncomm_positions_long_all"]) - number(row["noncomm_positions_short_all"])
        oi = number(row["open_interest_all"])
        if oi <= 0:
            continue
        for suffix, value, unit in (
            ("net", net, "contracts"),
            ("oi", oi, "contracts"),
            ("net_share", net / oi * 100, "percent"),
        ):
            output.append(
                EvidencePoint(
                    f"cftc.{asset}.{suffix}",
                    f"{asset} 非商业持仓 {suffix}（Legacy futures only）",
                    period,
                    value,
                    unit,
                    "weekly",
                )
            )
    if not output:
        raise ValueError("CFTC export has no recognized futures-only markets")
    return output


def export_urls(year: int) -> dict[str, tuple[str, str]]:
    treasury = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    )
    codes = ",".join(f"'{code}'" for code in COT_MARKETS)
    return {
        "eia_balance": ("eia_official", "https://ir.eia.gov/wpsr/table1.csv"),
        "eia_refinery": ("eia_official", "https://ir.eia.gov/wpsr/table9.csv"),
        "treasury_nominal": (
            "treasury_official",
            f"{treasury}?data=daily_treasury_yield_curve&field_tdr_date_value={year}",
        ),
        "treasury_real": (
            "treasury_official",
            f"{treasury}?data=daily_treasury_real_yield_curve&field_tdr_date_value={year}",
        ),
        "nyfed_sofr": (
            "nyfed_official",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/last/90.json",
        ),
        "nyfed_rrp": (
            "nyfed_official",
            "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/90.json",
        ),
        "cftc_positions": (
            "cftc_official",
            "https://publicreporting.cftc.gov/resource/6dca-aqww.json?"
            f"$where=cftc_contract_market_code in ({codes}) "
            f"AND report_date_as_yyyy_mm_dd >= '{year - 3}-01-01T00:00:00'"
            "&$order=report_date_as_yyyy_mm_dd DESC,cftc_contract_market_code&$limit=5000",
        ),
    }


def parse_export(dataset: str, content: bytes) -> list[EvidencePoint]:
    if dataset.startswith("eia_"):
        return parse_eia(content, "table1" if dataset == "eia_balance" else "table9")
    if dataset.startswith("treasury_"):
        return parse_treasury(content, dataset == "treasury_real")
    if dataset.startswith("nyfed_"):
        return parse_nyfed(content, "sofr" if dataset == "nyfed_sofr" else "rrp")
    if dataset == "cftc_positions":
        return parse_cftc(content)
    raise ValueError("unknown official evidence dataset")


async def fetch_export(
    provider: str, url: str, client: httpx.AsyncClient | None = None
) -> httpx.Response:
    transport = HttpProviderTransport(
        provider_key=provider,
        client=client,
        timeout_seconds=30,
        retry_policy=ProviderRetryPolicy(max_attempts=2),
    )
    return await transport.request("GET", url, headers={"User-Agent": USER_AGENT})
