from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from worldstate.application.data_foundation_service import record_provider_run
from worldstate.application.official_evidence_service import persist_export
from worldstate.application.series_evidence import load_series_evidence, match_series
from worldstate.db.base import Base
from worldstate.db.models import Observation
from worldstate.db.session import create_engine
from worldstate.provider_kit.official_evidence import (
    EvidencePoint,
    parse_cftc,
    parse_eia,
    parse_nyfed,
    parse_treasury,
)
from worldstate.reasoning.schema import EvidenceRule

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


def test_eia_sections_and_units_do_not_mix_spr_or_four_week_averages() -> None:
    raw = b"STUB_1,9/11/26,9/4/26,Difference\nCommercial (Excluding SPR),423.429,424.069,-0.640\nStrategic Petroleum Reserve (SPR),284,285,-1\nSTUB_1,STUB_2,9/11/26,9/4/26,Difference\nCrude Oil Supply ,(1) Domestic Production,13944,13947,-3\nProducts Supplied ,(30) Total,21255,19313,1942\n"  # noqa: E501
    points = parse_eia(raw, "table1")
    assert len(points) == 6
    assert points[0].key == "eia.crude_stocks"
    assert points[0].value == Decimal("423.429")
    assert points[2].unit == "thousand_barrels_per_day"
    with pytest.raises(ValueError, match="no recognized"):
        parse_eia(b"unrecognized", "table1")


def test_official_curve_and_funding_parsers() -> None:
    raw = b"<feed><properties><NEW_DATE>2026-09-18T00:00:00</NEW_DATE><BC_2YEAR>3.8</BC_2YEAR><TC_10YEAR>2.1</TC_10YEAR></properties></feed>"  # noqa: E501
    assert parse_treasury(raw, False)[0].key == "treasury.nominal_2y"
    assert parse_treasury(raw, True)[0].value == Decimal("2.1")
    sofr = json.dumps(
        {
            "refRates": [
                {"effectiveDate": "2026-09-18", "percentRate": 3.85, "volumeInBillions": 2955}
            ]
        }
    ).encode()
    assert len(parse_nyfed(sofr, "sofr")) == 2
    rrp = json.dumps(
        {
            "repo": {
                "operations": [
                    {
                        "operationType": "Reverse Repo",
                        "term": "Overnight",
                        "operationDate": "2026-09-18",
                        "totalAmtAccepted": 576000000,
                    },
                    {
                        "operationType": "Repo",
                        "term": "Overnight",
                        "operationDate": "2026-09-18",
                        "totalAmtAccepted": 99999999,
                    },
                ]
            }
        }
    ).encode()
    assert parse_nyfed(rrp, "rrp")[0].value == Decimal("0.576")


def test_cot_net_and_open_interest_share_are_not_trader_motives() -> None:
    raw = json.dumps(
        [
            {
                "cftc_contract_market_code": "088691",
                "futonly_or_combined": "FutOnly",
                "report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00",
                "noncomm_positions_long_all": "120",
                "noncomm_positions_short_all": "80",
                "open_interest_all": "200",
            }
        ]
    ).encode()
    points = parse_cftc(raw)
    assert [(p.key, p.value) for p in points] == [
        ("cftc.gold.net", Decimal(40)),
        ("cftc.gold.oi", Decimal(200)),
        ("cftc.gold.net_share", Decimal(20)),
    ]


@pytest.mark.asyncio
async def test_acquisition_cutoff_isolation_artifact_and_append_only(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'evidence.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    run = await record_provider_run(
        engine, provider_key="eia_official", operation="test", idempotency_key="one"
    )
    points = [
        EvidencePoint(
            "eia.production",
            "Production",
            date(2026, 9, 11),
            Decimal(13944),
            "thousand_barrels_per_day",
            "weekly",
        ),
        EvidencePoint(
            "eia.production",
            "Production",
            date(2026, 9, 4),
            Decimal(13947),
            "thousand_barrels_per_day",
            "weekly",
        ),
    ]
    kwargs: dict[str, Any] = dict(  # noqa: C408
        dataset="eia_balance",
        provider_key="eia_official",
        url="https://ir.eia.gov/wpsr/table1.csv",
        content=b"test export",
        content_type="text/csv",
        retrieved_at=NOW,
        points=points,
        run_id=run.id,
    )
    first = await persist_export(engine, **kwargs)
    assert first["inserted"] == 2
    assert (await persist_export(engine, **kwargs))["inserted"] == 0
    assert not (
        await load_series_evidence(
            engine, {"eia.production"}, "observed", NOW - timedelta(seconds=1)
        )
    )["eia.production"]["points"]
    assert not (await load_series_evidence(engine, {"eia.production"}, "fixture", NOW))[
        "eia.production"
    ]["points"]
    dataset = await load_series_evidence(engine, {"eia.production"}, "observed", NOW)
    assert dataset["eia.production"]["points"][0]["quality_flags"][3].startswith("artifact:")
    rule = EvidenceRule(
        key="production",
        label="产量",
        kind="series",
        series_key="eia.production",
        expected_direction="down",
        minimum_absolute=100,
        max_age_days=14,
    )
    assert match_series(rule, dataset, NOW)["state"] == "neutral"
    assert match_series(rule, dataset, NOW + timedelta(days=30))["missing_reason"] == "series_stale"
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(engine)() as session:
        rows = (await session.scalars(select(Observation))).all()
        assert all(row.available_at.replace(tzinfo=UTC) == NOW for row in rows if row.available_at)
    await engine.dispose()


def test_percentile_minimum_excludes_current_and_risk_is_explicit() -> None:
    rule = EvidenceRule(
        key="crowding",
        label="拥挤",
        kind="series",
        series_key="cot",
        expected_direction="up",
        transform="percentile",
        role="risk",
        minimum_absolute=90,
    )
    points = [{"id": str(i), "period": "2026-09-18", "value": 200 - i} for i in range(105)]
    data = {"cot": {"points": points[:20], "unit": "percent"}}
    assert match_series(rule, data, NOW)["missing_reason"] == "insufficient_percentile_history"
    data["cot"]["points"] = points
    result = match_series(rule, data, NOW)
    assert result["observed_value"] == 100
    assert result["sample_count"] == 104
    assert result["role"] == "risk"


def test_yield_change_uses_bp() -> None:
    rule = EvidenceRule(
        key="real",
        label="实际利率",
        kind="series",
        series_key="real",
        expected_direction="up",
        minimum_absolute=1,
    )
    data = {
        "real": {
            "unit": "percent",
            "frequency": "daily",
            "points": [
                {"id": "1", "period": "2026-09-18", "value": 2.10},
                {"id": "2", "period": "2026-09-17", "value": 2.05},
            ],
        }
    }
    result = match_series(rule, data, NOW)
    assert result["unit"] == "bp"
    assert result["observed_value"] == pytest.approx(5)


def test_risk_and_context_do_not_vote_for_directional_chain() -> None:
    from worldstate.application.reasoning_service import _step_result
    from worldstate.reasoning.schema import MechanismStep

    rules = [
        EvidenceRule(
            key=role,
            label=role,
            kind="series",
            series_key=role,
            expected_direction="up",
            role=role,
            minimum_absolute=1,
        )
        for role in ("directional", "risk", "context")
    ]
    data = {
        role: {
            "unit": "contracts",
            "frequency": "weekly",
            "points": [
                {"id": role + "1", "period": "2026-09-18", "value": value},
                {"id": role + "2", "period": "2026-09-11", "value": 10},
            ],
        }
        for role, value in (("directional", 5), ("risk", 20), ("context", 20))
    }
    result = _step_result(
        MechanismStep(key="test", label="Test", mechanism="Test", evidence_rules=rules),
        {},
        {},
        cutoff=NOW,
        series=data,
    )
    assert result["state"] == "contradicting"
    assert [check["state"] for check in result["checks"]] == [
        "contradicting",
        "supporting",
        "supporting",
    ]
