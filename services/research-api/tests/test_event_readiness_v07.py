from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from worldstate.application.analysis_orchestrator import _select_release_values
from worldstate.application.event_intraday_service import (
    evaluate_event_intraday_eligibility,
    evaluate_stored_event_intraday_manifest,
    normalize_event_minute_csv,
)
from worldstate.application.event_readiness import (
    evaluate_consensus_eligibility,
    evaluate_release_linked_minute_manifests,
)
from worldstate.db.models import ConsensusSnapshot, ReleaseValue


def _normalized_rows(start: datetime, *, missing: set[int] | None = None) -> dict[str, object]:
    missing = missing or set()
    lines = ["timestamp,open,high,low,close"]
    for index in range(-60, 61):
        if index in missing:
            continue
        at = start + timedelta(minutes=index)
        value = 100 + index / 100
        lines.append(f"{at.isoformat()},{value},{value + 1},{value - 1},{value}")
    return normalize_event_minute_csv(
        "\n".join(lines), instrument_key="gold_gc", timezone_name="UTC"
    )


def test_legacy_minute_manifest_without_policy_is_rejected() -> None:
    result = evaluate_stored_event_intraday_manifest(
        {"event_intraday_eligibility": "eligible"},
        data_mode="observed",
        row_count=121,
        interval_seconds=60,
    )
    assert result["eligible"] is False
    assert "missing_event_intraday_eligibility_metadata" in result["reasons"]


def test_stored_manifest_requires_matching_policy_and_mode() -> None:
    metadata = {
        "event_intraday_eligibility": "eligible",
        "is_fixture": False,
        "event_intraday_eligibility_v1": {
            "policy_version": "event-intraday-v1",
            "data_mode": "observed",
            "status": "eligible",
        },
    }
    result = evaluate_stored_event_intraday_manifest(
        metadata,
        data_mode="observed",
        row_count=121,
        interval_seconds=60,
        is_fixture=False,
    )
    assert result["eligible"] is True


def test_missing_key_window_is_reported_without_invalidating_broad_dataset() -> None:
    t0 = datetime(2030, 1, 2, 13, 30, tzinfo=UTC)
    normalized = _normalized_rows(t0, missing={-5})
    result = evaluate_event_intraday_eligibility(
        normalized,
        t0=t0,
        data_mode="observed",
        is_fixture=False,
        verified=True,
    )
    assert result["status"] == "eligible"
    assert result["window_coverage"]["pre_5m"]["available"] is False
    assert result["window_coverage"]["post_60m"]["available"] is True


def test_fomc_t0_is_not_lexical_and_uses_statement_stage() -> None:
    from types import SimpleNamespace

    release = SimpleNamespace(
        release_type="FOMC",
        scheduled_at=datetime(2030, 1, 1, 19, tzinfo=UTC),
        released_at=datetime(2030, 1, 1, 19, tzinfo=UTC),
    )
    stages = [
        SimpleNamespace(
            id="1",
            sequence=1,
            stage_key="statement",
            scheduled_at=datetime.fromisoformat("2030-01-01T14:00:00-05:00"),
            released_at=datetime.fromisoformat("2030-01-01T14:01:00-05:00"),
        ),
        SimpleNamespace(
            id="2",
            sequence=2,
            stage_key="press_conference",
            scheduled_at=datetime.fromisoformat("2030-01-01T14:30:00-05:00"),
            released_at=datetime.fromisoformat("2030-01-01T14:30:00-05:00"),
        ),
    ]
    from worldstate.application.event_intraday_service import resolve_release_t0

    assert resolve_release_t0(cast(Any, release), cast(Any, stages)) == datetime(
        2030, 1, 1, 19, 1, tzinfo=UTC
    )


def test_d_quality_browser_consensus_requires_explicit_policy_but_can_be_eligible() -> None:
    artifact_id = uuid.uuid4()
    snapshot = ConsensusSnapshot(
        id=uuid.uuid4(),
        macro_release_id=uuid.uuid4(),
        indicator_id=uuid.uuid4(),
        consensus_value=Decimal("0.1"),
        source_name="Trading Economics Survey Consensus",
        source_url="https://tradingeconomics.com/united-states/inflation-rate-mom",
        captured_at=datetime(2026, 8, 12, 3, 53, tzinfo=UTC),
        quality_grade="D",
        is_manual=False,
        data_mode="observed",
        source_artifact_id=artifact_id,
        metadata_json={
            "provider_metadata": {
                "consensus_field": "Forecast",
                "te_forecast_field": "TEForecast",
            },
            "te_forecast_used_as_consensus": False,
        },
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        content_hash="a" * 64,
        source_url=snapshot.source_url,
        retrieved_at=datetime(2026, 8, 12, 3, 53, 1, tzinfo=UTC),
        metadata_json={"acquisition_transport": "browser_capture"},
        is_fixture=False,
    )
    result = evaluate_consensus_eligibility(
        snapshot,
        cast(Any, artifact),
        t0=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
        release_data_mode="observed",
    )
    assert result.eligible is True
    assert "quality_grade_D_requires_careful_interpretation" in result.limitations


def test_consensus_post_t0_teforecast_and_missing_provenance_are_rejected() -> None:
    snapshot = ConsensusSnapshot(
        id=uuid.uuid4(),
        macro_release_id=uuid.uuid4(),
        indicator_id=uuid.uuid4(),
        consensus_value=Decimal("0.1"),
        source_name="Trading Economics Survey Consensus",
        source_url=None,
        captured_at=datetime(2026, 8, 12, 12, 31, tzinfo=UTC),
        quality_grade="D",
        is_manual=False,
        data_mode="observed",
        source_artifact_id=None,
        metadata_json={"te_forecast_used_as_consensus": True},
    )
    result = evaluate_consensus_eligibility(
        snapshot,
        None,
        t0=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
        release_data_mode="observed",
    )
    assert result.eligible is False
    assert "consensus_captured_at_must_be_before_t0" in result.reasons
    assert "consensus_provenance_incomplete" in result.reasons
    assert "consensus_source_semantics_unverified" in result.reasons


def test_initial_actual_captured_after_t0_is_selected_but_current_row_is_not() -> None:
    release_id = uuid.uuid4()
    indicator_id = uuid.uuid4()
    t0 = datetime(2026, 8, 12, 12, 30, tzinfo=UTC)

    def value(*, value: str, captured_at: datetime, metadata: dict[str, Any]) -> ReleaseValue:
        return ReleaseValue(
            id=uuid.uuid4(),
            macro_release_id=release_id,
            release_stage_id=None,
            indicator_id=indicator_id,
            value_kind="actual",
            value=Decimal(value),
            raw_value=value,
            data_version="official",
            valid_from=t0,
            captured_at=captured_at,
            is_initial=True,
            data_mode="observed",
            source_artifact_id=None,
            quality_id=None,
            metadata_json=metadata,
        )

    selected = _select_release_values(
        [
            value(value="3.5", captured_at=t0 + timedelta(minutes=1), metadata={}),
            value(
                value="3.4",
                captured_at=t0 + timedelta(days=1),
                metadata={"historical_initial_status": "not_reconstructable_from_current_bls_api"},
            ),
        ],
        {},
    )
    assert selected[(indicator_id, "actual")].value == Decimal("3.5")


def test_all_release_linked_minute_manifests_are_checked_without_asset_filter() -> None:
    legacy_non_event_asset = SimpleNamespace(
        id=uuid.uuid4(),
        metadata_json={"event_intraday_eligibility": "eligible"},
        row_count=121,
        interval_seconds=60,
    )
    eligible_manifest = SimpleNamespace(
        id=uuid.uuid4(),
        metadata_json={
            "event_intraday_eligibility": "eligible",
            "is_fixture": False,
            "event_intraday_eligibility_v1": {
                "policy_version": "event-intraday-v1",
                "data_mode": "observed",
                "status": "eligible",
            },
        },
        row_count=121,
        interval_seconds=60,
    )
    eligible, rejected = evaluate_release_linked_minute_manifests(
        cast(Any, [legacy_non_event_asset, eligible_manifest]), data_mode="observed"
    )
    assert [item.id for item in eligible] == [eligible_manifest.id]
    assert rejected[0]["manifest_id"] == str(legacy_non_event_asset.id)
