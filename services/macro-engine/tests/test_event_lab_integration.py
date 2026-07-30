import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from macro_engine import cli
from macro_engine.api.events import require_event_lab_write_access
from macro_engine.config import Settings
from macro_engine.main import create_app


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def migrate(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MACRO_DATABASE_URL", database_url(path))
    assert cli.run(["migrate"]) == cli.EXIT_OK
    capsys.readouterr()


def test_cpi_event_lab_migration_api_and_full_demo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "event-lab.db"
    migrate(path, monkeypatch, capsys)
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "data_quality_records",
        "macro_events",
        "event_indicators",
        "consensus_snapshots",
        "market_instruments",
        "market_bars",
        "event_window_metrics",
        "event_analyses",
    } <= tables

    settings = Settings(database_url=database_url(path))
    with TestClient(create_app(settings)) as client:
        status = client.get("/v1/events/lab/status")
        assert status.status_code == 200
        status_payload = status.json()
        assert status_payload["events"] == 9
        assert status_payload["market_bars"] == 18_963

        events = client.get("/v1/events").json()
        assert len(events) == 9
        demo_id = status_payload["demo_event_id"]
        demo = client.get(f"/v1/events/{demo_id}")
        assert demo.status_code == 200
        detail = demo.json()
        assert detail["bundle"]["classification"] == "全面偏热"
        assert len(detail["indicators"]) == 4
        assert len(detail["assets"]) == 7
        assert detail["historical"]["mode"] == "statistics"
        assert detail["historical"]["post_filter_count"] >= 5
        assert detail["confidence"] > 0
        assert "不能证明唯一因果" in detail["report"]
        assert any(asset["is_proxy"] for asset in detail["assets"])
        assert any(item["is_fixture"] for item in detail["data_quality"])
        assert client.get("/v1/events/not-a-uuid").status_code == 404
        assert client.get("/v1/events?event_type=US_NFP").json() == []

        consensus = {
            "indicator_key": "headline_mom",
            "consensus_value": 0.25,
            "consensus_source": "manual pre-release archive",
            "consensus_source_url": None,
            "consensus_captured_at": "2024-02-13T12:00:00Z",
            "consensus_quality": "reviewed",
            "consensus_is_manual": True,
            "consensus_is_fixture": False,
            "verification_notes": "entered during integration test",
        }
        captured = client.post(f"/v1/events/{demo_id}/consensus", json=consensus)
        assert captured.status_code == 200
        assert captured.json()["status"] == "consensus_snapshot_appended"
        duplicate = client.post(f"/v1/events/{demo_id}/consensus", json=consensus)
        assert duplicate.status_code == 200

        late_consensus = {
            **consensus,
            "consensus_source": "late invalid",
            "consensus_captured_at": "2024-02-13T14:00:00Z",
        }
        assert (
            client.post(f"/v1/events/{demo_id}/consensus", json=late_consensus).status_code == 400
        )

        csv_text = """timestamp,instrument_key,open,high,low,close,volume,interval_seconds
2024-02-13T13:29:00Z,gold_gc,2035,2036,2034,2035,1000,60
2024-02-13T13:30:00Z,gold_gc,2035,2035,2025,2027,4000,60
2024-02-13T13:31:00Z,gold_gc,2027,2028,2020,2022,3800,60
"""
        imported = client.post(
            f"/v1/events/{demo_id}/market-bars/import",
            json={
                "csv_text": csv_text,
                "instrument_key": "gold_gc",
                "provider_key": "test_csv",
                "source_name": "test export",
                "source_url": None,
                "acquired_at": "2024-02-14T00:00:00Z",
                "verified": True,
                "is_fixture": False,
                "verification_notes": "test-only CSV",
            },
        )
        assert imported.status_code == 200
        assert imported.json()["inserted"] == 3
        assert imported.json()["quality_grade"] == "B"
        assert client.post(f"/v1/events/{demo_id}/analyze").status_code == 200

        new_event = {
            "event_key": "us-cpi-2025-01-15-test",
            "title": "US CPI test import",
            "period_label": "2024-12",
            "release_at": "2025-01-15T13:30:00Z",
            "source_timezone": "America/New_York",
            "status": "released",
            "source_url": "https://www.bls.gov/cpi/",
            "data_version": "initial",
            "contamination_level": "none",
            "clean_window": True,
            "overlapping_events": [],
            "confounding_notes": [],
            "indicators": [
                {
                    "indicator_key": key,
                    "actual_value": actual,
                    "consensus_value": expected,
                    "previous_value": expected,
                    "revised_previous_value": expected,
                    "actual_source": "BLS manual entry",
                    "actual_source_url": "https://www.bls.gov/cpi/",
                    "actual_is_manual": True,
                    "actual_verified": True,
                    "actual_is_fixture": False,
                    "consensus_source": "manual archive",
                    "consensus_source_url": None,
                    "consensus_captured_at": "2025-01-14T13:30:00Z",
                    "consensus_quality": "reviewed",
                    "consensus_is_manual": True,
                    "consensus_is_fixture": False,
                    "verification_notes": "test record",
                }
                for key, actual, expected in (
                    ("headline_mom", 0.3, 0.2),
                    ("headline_yoy", 3.0, 2.9),
                    ("core_mom", 0.3, 0.2),
                    ("core_yoy", 3.2, 3.1),
                )
            ],
        }
        created = client.post("/v1/events/cpi", json=new_event)
        assert created.status_code == 200
        created_id = created.json()["event_id"]
        assert client.get(f"/v1/events/{created_id}").json()["data_mode"] == "observed"


def make_remote_request(settings: Settings) -> Request:
    app = FastAPI()
    app.state.settings = settings
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("203.0.113.1", 4312),
            "server": ("example.test", 443),
            "scheme": "https",
            "app": app,
        }
    )


def test_event_lab_write_guard_supports_token_and_rejects_remote_default() -> None:
    request = make_remote_request(Settings())
    with pytest.raises(HTTPException) as denied:
        require_event_lab_write_access(request, authorization=None, x_write_token=None)
    assert denied.value.status_code == 403

    credential = "".join(("secret", "-", "token"))
    enabled = Settings(enable_writes=True, write_token=credential)
    request = make_remote_request(enabled)
    require_event_lab_write_access(
        request,
        authorization=None,
        x_write_token=credential,
    )
    require_event_lab_write_access(
        request,
        authorization=f"Bearer {credential}",
        x_write_token=None,
    )

    local_app = FastAPI()
    local_app.state.settings = Settings()
    local_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8000),
            "scheme": "http",
            "app": local_app,
        }
    )
    require_event_lab_write_access(local_request, authorization=None, x_write_token=None)
