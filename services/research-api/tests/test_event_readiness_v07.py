from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from worldstate.application.event_intraday_service import (
    evaluate_event_intraday_eligibility,
    evaluate_stored_event_intraday_manifest,
    normalize_event_minute_csv,
)


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
