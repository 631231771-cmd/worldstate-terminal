"""Migrate the CPI Event Lab schema to the macro research terminal v3 schema.

Revision ID: 0003_macro_research_terminal
Revises: 0002_cpi_event_lab
Create Date: 2026-07-30

The migration preserves useful point-in-time series tables, replaces the
duplicated Release/MacroEvent concepts with MacroRelease, and removes the old
event-analysis tables only after count and relationship checks pass.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

from worldstate.db import models as v3_models  # noqa: F401
from worldstate.db.base import Base

revision: str = "0003_macro_research_terminal"
down_revision: str | None = "0002_cpi_event_lab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("d68c3757-7c53-49cf-a7d1-a2c05f027204")
_LEGACY_TABLES = (
    "data_quality_records",
    "macro_events",
    "event_indicators",
    "consensus_snapshots",
    "market_instruments",
    "market_bars",
    "event_window_metrics",
    "event_analyses",
)

_WINDOWS = (
    ("pre_60m", "T-60分钟至T0", -3600, 0, None),
    ("pre_15m", "T-15分钟至T0", -900, 0, None),
    ("post_1m", "T0至T+1分钟", 0, 60, None),
    ("post_5m", "T0至T+5分钟", 0, 300, None),
    ("post_15m", "T0至T+15分钟", 0, 900, None),
    ("post_30m", "T0至T+30分钟", 0, 1800, None),
    ("post_60m", "T0至T+60分钟", 0, 3600, None),
    ("post_4h", "T0至T+4小时", 0, 14400, None),
    ("us_cash_close", "当日美国现货收盘", 0, None, "us_cash_close"),
    ("next_close", "下一交易日收盘", 0, None, "next_trading_close"),
    ("day_5_close", "五个交易日后收盘", 0, None, "fifth_trading_close"),
)


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _stable_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, value)


def _json(value: object, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"unsupported datetime value: {type(value).__name__}")


def _rows(connection: sa.Connection, table: sa.Table) -> list[Mapping[str, Any]]:
    return list(connection.execute(sa.select(table)).mappings())


def _legacy_table(connection: sa.Connection, name: str) -> sa.Table:
    return sa.Table(f"{name}_v2", sa.MetaData(), autoload_with=connection)


def _copy_quality(connection: sa.Connection) -> None:
    source = _legacy_table(connection, "data_quality_records")
    target = Base.metadata.tables["data_quality_records"]
    records = []
    for row in _rows(connection, source):
        records.append(
            {
                "id": _uuid(row["id"]),
                "subject_type": "migrated_v2",
                "subject_id": None,
                "source_name": row["source_name"],
                "source_url": row["source_url"],
                "source_type": row["source_type"],
                "acquired_at": row["acquired_at"],
                "is_manual": row["is_manual"],
                "is_verified": row["is_verified"],
                "is_fixture": row["is_fixture"],
                "is_proxy": row["is_proxy"],
                "latency_seconds": row["latency_seconds"],
                "granularity_seconds": row["granularity_seconds"],
                "missing_reason": row["missing_reason"],
                "quality_grade": row["quality_grade"],
                "verification_notes": row["verification_notes"],
                "metadata_json": _json(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
        )
    if records:
        connection.execute(target.insert(), records)


def _copy_releases(
    connection: sa.Connection,
) -> tuple[dict[str, uuid.UUID], dict[uuid.UUID, uuid.UUID]]:
    events = _legacy_table(connection, "macro_events")
    indicators = _legacy_table(connection, "event_indicators")
    source_artifacts = Base.metadata.tables["source_artifacts"]
    indicator_target = Base.metadata.tables["indicators"]
    release_target = Base.metadata.tables["macro_releases"]
    stage_target = Base.metadata.tables["release_stages"]
    value_target = Base.metadata.tables["release_values"]

    event_rows = _rows(connection, events)
    indicator_rows = _rows(connection, indicators)
    indicator_keys = sorted({str(row["indicator_key"]) for row in indicator_rows})
    weights: dict[str, float] = {}
    for row in indicator_rows:
        weights[str(row["indicator_key"])] = float(row["bundle_weight"])

    indicator_ids: dict[str, uuid.UUID] = {}
    indicator_records = []
    for key in indicator_keys:
        sample = next(row for row in indicator_rows if row["indicator_key"] == key)
        indicator_id = _stable_uuid(f"indicator:{key}")
        indicator_ids[key] = indicator_id
        indicator_records.append(
            {
                "id": indicator_id,
                "indicator_key": key,
                "name": sample["title"],
                "family": "inflation"
                if "cpi" in key or key.startswith(("headline", "core"))
                else "macro",
                "country": "USA",
                "unit": sample["unit"],
                "periodicity": "monthly",
                "description": "Migrated from the CPI Event Lab indicator bundle.",
                "hotter_when_higher": sample["hotter_when_higher"],
                "bundle_weight": weights[key],
                "active": True,
                "metadata_json": {"migration_source": "event_indicators"},
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
    if indicator_records:
        connection.execute(indicator_target.insert(), indicator_records)

    stage_ids: dict[uuid.UUID, uuid.UUID] = {}
    release_records = []
    stage_records = []
    artifact_records = []
    event_artifacts: dict[uuid.UUID, uuid.UUID] = {}
    for event in event_rows:
        event_id = _uuid(event["id"])
        artifact_id = _stable_uuid(f"artifact:{event['event_key']}")
        event_artifacts[event_id] = artifact_id
        content_hash = hashlib.sha256(str(event["source_url"]).encode()).hexdigest()
        artifact_records.append(
            {
                "id": artifact_id,
                "source_key": f"{event['event_key']}:official-release",
                "provider_key": "migration_v2",
                "artifact_type": "official_release",
                "title": event["title"],
                "source_url": event["source_url"],
                "published_at": event["release_at"],
                "retrieved_at": event["created_at"],
                "content_hash": content_hash,
                "license_name": None,
                "citation_text": f"{event['title']} ({event['period_label']})",
                "is_fixture": event["is_fixture"],
                "metadata_json": {"migration_source": "macro_events"},
                "created_at": event["created_at"],
                "updated_at": event["updated_at"],
            }
        )
        release_records.append(
            {
                "id": event_id,
                "release_key": event["event_key"],
                "release_type": event["event_type"],
                "title": event["title"],
                "country": event["country"],
                "period_label": event["period_label"],
                "scheduled_at": event["release_at"],
                "released_at": event["release_at"],
                "source_timezone": event["source_timezone"],
                "status": event["status"],
                "data_version": event["data_version"],
                "source_artifact_id": artifact_id,
                "primary_quality_id": (
                    _uuid(event["primary_quality_id"])
                    if event["primary_quality_id"] is not None
                    else None
                ),
                "contamination_level": event["contamination_level"],
                "clean_window": event["clean_window"],
                "overlapping_events": _json(event["overlapping_events"], []),
                "confounding_notes": _json(event["confounding_notes"], []),
                "metadata_json": {
                    **_json(event["metadata_json"], {}),
                    "migration_source": "macro_events",
                },
                "created_at": event["created_at"],
                "updated_at": event["updated_at"],
            }
        )
        stage_id = _stable_uuid(f"release-stage:{event_id}:release")
        stage_ids[event_id] = stage_id
        stage_records.append(
            {
                "id": stage_id,
                "macro_release_id": event_id,
                "stage_key": "release",
                "title": "数据公布",
                "sequence": 1,
                "scheduled_at": event["release_at"],
                "released_at": event["release_at"],
                "status": "released",
                "source_artifact_id": artifact_id,
                "metadata_json": {"migration_source": "macro_events"},
                "created_at": event["created_at"],
                "updated_at": event["updated_at"],
            }
        )

    if artifact_records:
        connection.execute(source_artifacts.insert(), artifact_records)
        connection.execute(release_target.insert(), release_records)
        connection.execute(stage_target.insert(), stage_records)

    value_records = []
    for row in indicator_rows:
        event_id = _uuid(row["event_id"])
        indicator_id = indicator_ids[str(row["indicator_key"])]
        captured_at = next(
            event["release_at"] for event in event_rows if _uuid(event["id"]) == event_id
        )
        values = (
            ("actual", row["actual_value"], True),
            ("previous", row["previous_value"], False),
            ("revised_previous", row["revised_previous_value"], False),
            ("first_release", row["first_release_value"], True),
        )
        for value_kind, value, is_initial in values:
            if value is None:
                continue
            value_records.append(
                {
                    "id": _stable_uuid(
                        f"release-value:{event_id}:{indicator_id}:{value_kind}:{row['data_version']}"
                    ),
                    "macro_release_id": event_id,
                    "release_stage_id": stage_ids[event_id],
                    "indicator_id": indicator_id,
                    "value_kind": value_kind,
                    "value": value,
                    "raw_value": str(value),
                    "data_version": row["data_version"],
                    "valid_from": captured_at,
                    "captured_at": captured_at,
                    "is_initial": is_initial,
                    "source_artifact_id": event_artifacts[event_id],
                    "quality_id": (
                        _uuid(row["actual_quality_id"])
                        if row["actual_quality_id"] is not None
                        else None
                    ),
                    "metadata_json": {
                        "raw_surprise": (
                            float(row["raw_surprise"]) if row["raw_surprise"] is not None else None
                        ),
                        "relative_surprise": row["relative_surprise"],
                        "standardized_surprise": row["standardized_surprise"],
                        "surprise_direction": row["surprise_direction"],
                        "migration_source": "event_indicators",
                    },
                }
            )
    if value_records:
        connection.execute(value_target.insert(), value_records)
    return indicator_ids, stage_ids


def _copy_consensus(
    connection: sa.Connection,
    indicator_ids: dict[str, uuid.UUID],
) -> None:
    source = _legacy_table(connection, "consensus_snapshots")
    target = Base.metadata.tables["consensus_snapshots"]
    records = []
    for row in _rows(connection, source):
        records.append(
            {
                "id": _uuid(row["id"]),
                "macro_release_id": _uuid(row["event_id"]),
                "indicator_id": indicator_ids[str(row["indicator_key"])],
                "consensus_value": row["consensus_value"],
                "source_name": row["consensus_source"],
                "source_url": row["consensus_source_url"],
                "captured_at": row["consensus_captured_at"],
                "quality_grade": row["consensus_quality"],
                "is_manual": row["consensus_is_manual"],
                "verification_notes": row["verification_notes"],
                "source_artifact_id": None,
                "quality_id": (_uuid(row["quality_id"]) if row["quality_id"] is not None else None),
                "created_at": row["created_at"],
            }
        )
    if records:
        connection.execute(target.insert(), records)


def _copy_market(
    connection: sa.Connection,
) -> tuple[dict[uuid.UUID, uuid.UUID | None], dict[str, uuid.UUID]]:
    instruments = _legacy_table(connection, "market_instruments")
    bars = _legacy_table(connection, "market_bars")
    instrument_target = Base.metadata.tables["market_instruments"]
    contract_target = Base.metadata.tables["futures_contracts"]
    bar_target = Base.metadata.tables["market_bars"]

    contract_ids: dict[uuid.UUID, uuid.UUID | None] = {}
    key_to_id: dict[str, uuid.UUID] = {}
    instrument_records = []
    contract_records = []
    for row in _rows(connection, instruments):
        instrument_id = _uuid(row["id"])
        key_to_id[str(row["canonical_key"])] = instrument_id
        contract_code = row["contract_code"]
        instrument_records.append(
            {
                "id": instrument_id,
                "canonical_key": row["canonical_key"],
                "symbol": row["symbol"],
                "title": row["title"],
                "asset_class": row["asset_class"],
                "instrument_type": "futures_proxy" if row["is_proxy"] else "futures",
                "exchange": row["exchange"],
                "quote_unit": row["quote_unit"],
                "measurement_type": row["measurement_type"],
                "source_timezone": row["source_timezone"],
                "is_proxy": row["is_proxy"],
                "proxy_for": row["proxy_for"],
                "active": row["active"],
                "metadata_json": {
                    **_json(row["metadata_json"], {}),
                    "root_symbol": row["root_symbol"],
                    "legacy_contract_code": contract_code,
                    "migration_source": "market_instruments",
                },
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
        if contract_code:
            contract_id = _stable_uuid(f"contract:{instrument_id}:{contract_code}")
            contract_ids[instrument_id] = contract_id
            contract_records.append(
                {
                    "id": contract_id,
                    "instrument_id": instrument_id,
                    "contract_code": contract_code,
                    "provider_symbol": row["symbol"],
                    "first_trade_date": None,
                    "last_trade_date": None,
                    "expiry_date": None,
                    "roll_start_at": None,
                    "roll_end_at": None,
                    "is_proxy": row["is_proxy"],
                    "metadata_json": {"migration_source": "market_instruments"},
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        else:
            contract_ids[instrument_id] = None
    if instrument_records:
        connection.execute(instrument_target.insert(), instrument_records)
    if contract_records:
        connection.execute(contract_target.insert(), contract_records)

    batch: list[dict[str, Any]] = []
    for row in _rows(connection, bars):
        instrument_id = _uuid(row["instrument_id"])
        contract_code = str(row["contract_code"] or "")
        batch.append(
            {
                "id": row["id"],
                "instrument_id": instrument_id,
                "futures_contract_id": contract_ids[instrument_id],
                "timestamp": row["timestamp"],
                "interval_seconds": row["interval_seconds"],
                "open_value": row["open_value"],
                "high_value": row["high_value"],
                "low_value": row["low_value"],
                "close_value": row["close_value"],
                "volume": row["volume"],
                "provider_key": row["provider_key"],
                "source_symbol": row["source_symbol"],
                "contract_code": contract_code,
                "is_regular_session": None,
                "quality_id": (_uuid(row["quality_id"]) if row["quality_id"] is not None else None),
                "fetched_at": row["fetched_at"],
                "metadata_json": {
                    **_json(row["metadata_json"], {}),
                    "migration_source": "market_bars",
                },
            }
        )
        if len(batch) >= 1000:
            connection.execute(bar_target.insert(), batch)
            batch.clear()
    if batch:
        connection.execute(bar_target.insert(), batch)
    return contract_ids, key_to_id


def _seed_window_definitions(connection: sa.Connection) -> dict[str, int]:
    target = Base.metadata.tables["event_window_definitions"]
    connection.execute(
        target.insert(),
        [
            {
                "window_key": key,
                "label": label,
                "start_offset_seconds": start,
                "end_offset_seconds": end,
                "close_rule": close_rule,
                "anchor_stage_key": "release",
                "sequence": index,
                "active": True,
                "methodology_notes": "Migrated v3 canonical event-window definition.",
            }
            for index, (key, label, start, end, close_rule) in enumerate(_WINDOWS, start=1)
        ],
    )
    return {
        str(row["window_key"]): int(row["id"])
        for row in connection.execute(sa.select(target)).mappings()
    }


def _copy_analysis(
    connection: sa.Connection,
    stage_ids: dict[uuid.UUID, uuid.UUID],
    instrument_keys: dict[str, uuid.UUID],
    window_ids: dict[str, int],
) -> None:
    legacy_analyses = _legacy_table(connection, "event_analyses")
    legacy_windows = _legacy_table(connection, "event_window_metrics")
    legacy_events = _legacy_table(connection, "macro_events")
    analyses = Base.metadata.tables["analysis_runs"]
    window_results = Base.metadata.tables["event_window_results"]
    reactions = Base.metadata.tables["market_reactions"]
    explanations = Base.metadata.tables["explanations"]
    matches = Base.metadata.tables["historical_matches"]
    reports = Base.metadata.tables["report_artifacts"]

    event_metadata = {
        _uuid(row["id"]): _json(row["metadata_json"], {})
        for row in _rows(connection, legacy_events)
    }
    analysis_rows = _rows(connection, legacy_analyses)
    run_by_event: dict[uuid.UUID, uuid.UUID] = {}
    analysis_records = []
    for row in analysis_rows:
        event_id = _uuid(row["event_id"])
        run_id = _uuid(row["id"])
        run_by_event[event_id] = run_id
        analysis_records.append(
            {
                "id": run_id,
                "macro_release_id": event_id,
                "methodology_version": row["methodology_version"],
                "code_version": "v2-migration",
                "status": "completed",
                "started_at": row["generated_at"],
                "completed_at": row["generated_at"],
                "regime_snapshot_id": None,
                "composite_classification": row["composite_classification"],
                "composite_surprise_score": event_metadata[event_id].get("bundle_score"),
                "confidence": row["confidence"],
                "facts_json": _json(row["facts_json"], []),
                "earliest_reactions_json": _json(row["earliest_reactions_json"], []),
                "data_gaps_json": _json(row["data_gaps_json"], []),
                "parameters_json": {
                    "migration_source": "event_analyses",
                    "historical_v2": _json(row["historical_json"], {}),
                },
            }
        )
    if analysis_records:
        connection.execute(analyses.insert(), analysis_records)

    window_records = []
    grouped_windows: dict[tuple[uuid.UUID, uuid.UUID], list[Mapping[str, Any]]] = defaultdict(list)
    for row in _rows(connection, legacy_windows):
        event_id = _uuid(row["event_id"])
        instrument_id = _uuid(row["instrument_id"])
        grouped_windows[(event_id, instrument_id)].append(row)
        window_key = str(row["window_key"])
        if event_id not in run_by_event or window_key not in window_ids:
            continue
        metadata = _json(row["metadata_json"], {})
        window_records.append(
            {
                "id": _uuid(row["id"]),
                "analysis_run_id": run_by_event[event_id],
                "release_stage_id": stage_ids[event_id],
                "instrument_id": instrument_id,
                "window_definition_id": window_ids[window_key],
                "start_at": row["start_at"],
                "end_at": row["end_at"],
                "start_value": row["start_value"],
                "end_value": row["end_value"],
                "change_absolute": row["change_absolute"],
                "return_percent": row["return_percent"],
                "change_basis_points": None,
                "max_up_percent": row["max_up_percent"],
                "max_down_percent": row["max_down_percent"],
                "realized_volatility": row["realized_volatility"],
                "volume_change_percent": row["volume_change_percent"],
                "coverage_ratio": row["coverage_ratio"],
                "direction": row["direction"],
                "spike_fade": row["spike_fade"],
                "dip_recovery": row["dip_recovery"],
                "direction_reversal": row["direction_reversal"],
                "granularity_seconds": row["granularity_seconds"],
                "provider_key": row["provider_key"],
                "quality_grade": row["quality_grade"],
                "missing_reason": metadata.get("missing_reason"),
                "calculated_at": row["calculated_at"],
                "metadata_json": {
                    **metadata,
                    "migration_source": "event_window_metrics",
                },
            }
        )
    if window_records:
        connection.execute(window_results.insert(), window_records)

    analysis_by_event = {_uuid(row["event_id"]): row for row in analysis_rows}
    reaction_records = []
    for (event_id, instrument_id), items in grouped_windows.items():
        analysis = analysis_by_event.get(event_id)
        if analysis is None:
            continue
        earliest_by_key = {
            str(item.get("instrument_key")): item
            for item in _json(analysis["earliest_reactions_json"], [])
        }
        key = next(
            (name for name, value in instrument_keys.items() if value == instrument_id),
            str(instrument_id),
        )
        earliest = earliest_by_key.get(key, {})
        strongest = max(
            items,
            key=lambda item: abs(float(item["return_percent"] or 0.0)),
        )
        reaction_records.append(
            {
                "id": _stable_uuid(f"reaction:{run_by_event[event_id]}:{instrument_id}"),
                "analysis_run_id": run_by_event[event_id],
                "release_stage_id": stage_ids[event_id],
                "instrument_id": instrument_id,
                "earliest_significant_at": _datetime(earliest.get("detected_at")),
                "latency_seconds": earliest.get("lag_seconds"),
                "pre_event_volatility": earliest.get("pre_event_volatility"),
                "significance_threshold": earliest.get("threshold_percent"),
                "confirmation_bars": int(earliest.get("confirmation_bars", 2)),
                "initial_direction": earliest.get("direction", strongest["direction"]),
                "strongest_window_key": strongest["window_key"],
                "reaction_strength": abs(float(strongest["return_percent"] or 0.0)),
                "lead_rank": None,
                "spike_fade": any(bool(item["spike_fade"]) for item in items),
                "dip_recovery": any(bool(item["dip_recovery"]) for item in items),
                "direction_reversal": any(bool(item["direction_reversal"]) for item in items),
                "granularity_seconds": int(strongest["granularity_seconds"]),
                "limitations_json": (
                    [str(earliest["limitation"])] if earliest.get("limitation") else []
                ),
            }
        )
    if reaction_records:
        connection.execute(reactions.insert(), reaction_records)

    explanation_records = []
    match_records = []
    report_records = []
    for row in analysis_rows:
        run_id = _uuid(row["id"])
        event_id = _uuid(row["event_id"])
        explanation_items = _json(row["explanations_json"], [])
        for rank, item in enumerate(explanation_items, start=1):
            evidence = [
                {"statement": text, "source": "migrated_v2_rule"}
                for text in item.get("evidence", [])
            ]
            explanation_records.append(
                {
                    "id": _stable_uuid(f"explanation:{run_id}:{rank}"),
                    "analysis_run_id": run_id,
                    "explanation_type": "primary" if rank == 1 else "competitive",
                    "rank": rank,
                    "title": item.get("label", item.get("rule", "迁移解释")),
                    "summary": item.get("inference", ""),
                    "confidence": float(row["confidence"]),
                    "causal_language": item.get("certainty", "plausible_inference"),
                    "mechanism_steps_json": [],
                    "confirming_evidence_json": evidence,
                    "contradicting_evidence_json": [],
                    "unresolved_json": [],
                    "rule_key": item.get("rule"),
                }
            )
        historical = _json(row["historical_json"], {})
        for rank, item in enumerate(historical.get("similar_cases", []), start=1):
            matched = item.get("event_id")
            if not matched:
                continue
            match_records.append(
                {
                    "id": _stable_uuid(f"historical:{run_id}:{matched}"),
                    "analysis_run_id": run_id,
                    "matched_release_id": _uuid(matched),
                    "similarity_score": float(item.get("similarity", 0.0)),
                    "rank": rank,
                    "included": True,
                    "filters_json": [
                        str(value.get("condition")) for value in historical.get("filters", [])
                    ],
                    "comparable_metrics_json": item.get("returns", {}),
                    "exclusion_reason": None,
                }
            )
        report_text = str(row["report_text"])
        evidence_hash = hashlib.sha256(
            json.dumps(
                {
                    "event_id": str(event_id),
                    "facts": _json(row["facts_json"], []),
                    "explanations": explanation_items,
                    "historical": historical,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        report_records.append(
            {
                "id": _stable_uuid(f"report:{run_id}:deterministic"),
                "analysis_run_id": run_id,
                "format": "markdown",
                "content": report_text,
                "evidence_pack_hash": evidence_hash,
                "generator": "migrated_v2_deterministic",
                "model_name": None,
                "generated_at": row["generated_at"],
                "validation_json": {
                    "status": "migrated_requires_v3_reanalysis",
                    "causal_language_checked": False,
                },
            }
        )
    if explanation_records:
        connection.execute(explanations.insert(), explanation_records)
    if match_records:
        connection.execute(matches.insert(), match_records)
    if report_records:
        connection.execute(reports.insert(), report_records)


def _migrate_sync_runs(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    target = Base.metadata.tables["provider_runs"]
    if "sync_runs" not in inspector.get_table_names():
        return
    source = sa.Table("sync_runs", sa.MetaData(), autoload_with=connection)
    columns = {column.name for column in source.columns}
    records = []
    for row in _rows(connection, source):
        started_at = row.get("started_at") or row.get("created_at") or datetime.now(UTC)
        records.append(
            {
                "id": _stable_uuid(f"sync-run:{row['id']}"),
                "provider_key": str(row.get("provider_key") or "legacy_sync"),
                "operation": str(row.get("run_type") or row.get("mode") or "sync"),
                "status": str(row.get("status") or "unknown"),
                "started_at": started_at,
                "completed_at": row.get("completed_at") if "completed_at" in columns else None,
                "records_read": int(row.get("records_read") or 0),
                "records_written": int(row.get("records_written") or 0),
                "source_artifact_id": None,
                "quality_grade": "UNKNOWN",
                "input_json": {"legacy_id": str(row["id"])},
                "output_json": {},
                "warnings_json": [],
                "error_message": row.get("error_message"),
            }
        )
    if records:
        connection.execute(target.insert(), records)


def _verify(connection: sa.Connection) -> None:
    checks = (
        ("macro_events_v2", "macro_releases"),
        ("event_analyses_v2", "analysis_runs"),
        ("event_window_metrics_v2", "event_window_results"),
        ("market_bars_v2", "market_bars"),
        ("market_instruments_v2", "market_instruments"),
        ("consensus_snapshots_v2", "consensus_snapshots"),
        ("data_quality_records_v2", "data_quality_records"),
    )
    for legacy_name, target_name in checks:
        legacy_count = int(
            connection.execute(sa.text(f'SELECT COUNT(*) FROM "{legacy_name}"')).scalar_one()
        )
        target_count = int(
            connection.execute(sa.text(f'SELECT COUNT(*) FROM "{target_name}"')).scalar_one()
        )
        if legacy_count != target_count:
            raise RuntimeError(
                f"v3 migration count mismatch: {legacy_name}={legacy_count}, "
                f"{target_name}={target_count}"
            )
    orphan_count = int(
        connection.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM release_values rv
                LEFT JOIN macro_releases mr ON mr.id = rv.macro_release_id
                LEFT JOIN indicators i ON i.id = rv.indicator_id
                WHERE mr.id IS NULL OR i.id IS NULL
                """
            )
        ).scalar_one()
    )
    if orphan_count:
        raise RuntimeError(f"v3 migration produced {orphan_count} orphan release values")


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names())
    missing = set(_LEGACY_TABLES) - existing
    if missing:
        raise RuntimeError(f"database v2 prerequisite tables missing: {sorted(missing)}")

    # Named indexes are global in SQLite. Remove the two names reused by v3
    # before renaming their parent tables.
    op.drop_index("ix_data_quality_source_acquired", table_name="data_quality_records")
    op.drop_index("ix_market_bars_instrument_time", table_name="market_bars")
    for table_name in _LEGACY_TABLES:
        op.rename_table(table_name, f"{table_name}_v2")

    Base.metadata.create_all(bind=connection, checkfirst=True)
    _copy_quality(connection)
    indicator_ids, stage_ids = _copy_releases(connection)
    _copy_consensus(connection, indicator_ids)
    _, instrument_keys = _copy_market(connection)
    window_ids = _seed_window_definitions(connection)
    _copy_analysis(connection, stage_ids, instrument_keys, window_ids)
    _migrate_sync_runs(connection)
    _verify(connection)

    # Duplicate/empty event concepts are removed after successful verification.
    for table_name in (
        "event_window_metrics_v2",
        "event_analyses_v2",
        "market_bars_v2",
        "market_instruments_v2",
        "consensus_snapshots_v2",
        "event_indicators_v2",
        "macro_events_v2",
        "data_quality_records_v2",
        "release_series",
        "releases",
    ):
        if table_name in sa.inspect(connection).get_table_names():
            op.drop_table(table_name)

    # Old monitor-only research scaffolding had no user data. State definitions
    # are reproducible configuration, not observations; v3 regime snapshots
    # replace them.
    for table_name in (
        "causal_edges",
        "causal_nodes",
        "thesis_evidence",
        "thesis_conditions",
        "thesis_snapshots",
        "theses",
        "state_components",
        "state_snapshots",
        "state_definitions",
        "sync_runs",
    ):
        if table_name in sa.inspect(connection).get_table_names():
            op.drop_table(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "Database v3 downgrade is intentionally unsupported. "
        "Restore the pre-v3 backup recorded in docs/macro/migration-baseline.md."
    )
