"""Immutable AnalysisRun manifest hashing, replay, and comparison."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.db.models import AnalysisRun


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def output_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Hash only deterministic research output; ignore database/run identifiers."""

    return canonical_hash(snapshot)


def replay_output_snapshot(
    snapshot: dict[str, Any], expected_hash: str | None
) -> dict[str, object]:
    actual_hash = output_snapshot_hash(snapshot)
    return {
        "replayed": bool(expected_hash) and actual_hash == expected_hash,
        "expected_output_hash": expected_hash,
        "replayed_output_hash": actual_hash,
        "core_result": snapshot,
    }


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _get_run(engine: AsyncEngine, run_id: str) -> AnalysisRun | None:
    try:
        value = uuid.UUID(run_id)
    except ValueError:
        return None
    async with _factory(engine)() as session:
        return await session.get(AnalysisRun, value)


async def get_analysis_manifest(engine: AsyncEngine, run_id: str) -> dict[str, object] | None:
    run = await _get_run(engine, run_id)
    if run is None:
        return None
    return {
        "run_id": str(run.id),
        "status": run.status,
        "reproducibility_status": run.reproducibility_status,
        "input_snapshot_hash": run.input_snapshot_hash,
        "config_hash": run.config_hash,
        "output_hash": run.output_hash,
        "release_snapshot": run.release_snapshot_json,
        "release_value_ids": run.release_value_ids_json,
        "consensus_snapshot_ids": run.consensus_snapshot_ids_json,
        "release_stage_ids": run.release_stage_ids_json,
        "market_dataset": run.market_dataset_manifest_json,
        "market_dataset_hash": run.market_dataset_hash,
        "historical_sample_manifest": run.historical_sample_manifest_json,
        "historical_sample_hash": run.historical_sample_hash,
        "providers": run.provider_manifest_json,
        "source_artifact_ids": run.source_artifact_ids_json,
        "algorithm_versions": run.algorithm_versions_json,
        "rule_versions": run.rule_versions_json,
        "parameters": run.analysis_parameters_json,
        "output_snapshot": run.parameters_json.get("output_snapshot"),
        "failure": {
            "stage": run.failure_stage,
            "type": run.error_type,
            "message": run.error_message,
        },
    }


async def replay_analysis_run(engine: AsyncEngine, run_id: str) -> dict[str, object] | None:
    run = await _get_run(engine, run_id)
    if run is None:
        return None
    snapshot = run.parameters_json.get("output_snapshot")
    if run.reproducibility_status != "complete" or not isinstance(snapshot, dict):
        return {
            "source_run_id": run_id,
            "replayed": False,
            "reason": "legacy run lacks a complete immutable input/output snapshot",
            "expected_output_hash": run.output_hash,
        }
    market_hash = canonical_hash(run.market_dataset_manifest_json)
    config_hash = canonical_hash(
        {
            "algorithms": run.algorithm_versions_json,
            "rules": run.rule_versions_json,
            "parameters": run.analysis_parameters_json,
        }
    )
    sample_manifest = run.historical_sample_manifest_json.get("sample_manifest")
    historical_hash = (
        hashlib.sha256(json.dumps(sample_manifest, sort_keys=True).encode()).hexdigest()
        if isinstance(sample_manifest, list)
        else None
    )
    input_hash = canonical_hash(
        {
            "release": run.release_snapshot_json,
            "release_value_ids": run.release_value_ids_json,
            "consensus_snapshot_ids": run.consensus_snapshot_ids_json,
            "stage_ids": run.release_stage_ids_json,
            "market_hash": market_hash,
            "historical_sample_hash": historical_hash,
            "config_hash": config_hash,
        }
    )
    output_replay = replay_output_snapshot(snapshot, run.output_hash)
    checks = {
        "market_dataset_hash": market_hash == run.market_dataset_hash,
        "historical_sample_hash": historical_hash == run.historical_sample_hash,
        "config_hash": config_hash == run.config_hash,
        "input_snapshot_hash": input_hash == run.input_snapshot_hash,
        "output_hash": output_replay["replayed"],
    }
    replayed = all(checks.values())
    return {
        "source_run_id": run_id,
        "replay_mode": "immutable_snapshot_recalculation",
        "replayed": replayed,
        "checks": checks,
        "expected_input_hash": run.input_snapshot_hash,
        "replayed_input_hash": input_hash,
        **{key: value for key, value in output_replay.items() if key != "replayed"},
    }


async def diff_analysis_runs(
    engine: AsyncEngine, left_id: str, right_id: str
) -> dict[str, object] | None:
    left = await get_analysis_manifest(engine, left_id)
    right = await get_analysis_manifest(engine, right_id)
    if left is None or right is None:
        return None
    keys = (
        "input_snapshot_hash",
        "config_hash",
        "market_dataset_hash",
        "historical_sample_hash",
        "output_hash",
    )
    return {
        "left_run_id": left_id,
        "right_run_id": right_id,
        "differences": {
            key: {
                "left": left[key],
                "right": right[key],
                "equal": left[key] == right[key],
            }
            for key in keys
        },
    }


__all__ = [
    "canonical_hash",
    "diff_analysis_runs",
    "get_analysis_manifest",
    "output_snapshot_hash",
    "replay_analysis_run",
    "replay_output_snapshot",
]
