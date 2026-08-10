from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from worldstate.api.v2.data_router import (
    DEFAULT_ASSETS,
    DEFAULT_EVENT_TYPES,
    build_data_coverage,
    build_provider_status,
    estimate_backfill_payload,
    normalize_multi_operation_result,
    run_data_reconciliation,
)
from worldstate.api.v2.schemas import BackfillRequestInput
from worldstate.application.analysis_orchestrator import (
    _pre_event_regime_context,
    _release_data_provenance,
)
from worldstate.application.backfill_service import BackfillRequest, estimate_backfill
from worldstate.application.data_manifest_service import record_market_data_manifest
from worldstate.application.reconciliation_service import (
    reconcile_values,
    record_market_reconciliation,
)
from worldstate.cli import run
from worldstate.config import Settings
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import (
    ConsensusSnapshot,
    DataQualityRecord,
    EconomicEntity,
    Indicator,
    MacroRelease,
    MarketInstrument,
    Observation,
    Provider,
    ReleaseValue,
    Series,
    SyncJob,
    SyncJobRun,
)
from worldstate.db.session import create_engine


def test_health_and_fixed_provider_status_are_secret_safe(client: TestClient) -> None:
    health = client.get("/v2/health")
    assert health.status_code == 200
    foundation = health.json()["data_foundation"]
    assert foundation == {
        "demo_mode": True,
        "scheduler_enabled": False,
        "paid_download_enabled": False,
        "databento_budget_limit_usd": 0.0,
        "credentials_exposed": False,
    }

    response = client.get("/v2/data/providers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["secrets_returned"] is False
    providers = {item["provider_id"]: item for item in payload["items"]}
    assert {
        "fred_alfred",
        "bls_official",
        "federal_reserve_fomc",
        "trading_economics_consensus",
        "databento_market",
    }.issubset(providers)
    assert {
        "ecb_data_portal",
        "bank_of_england_iadb",
        "boj_public",
        "china_official_public",
    }.issubset(providers)
    assert providers["bls_official"]["configured"] is True
    assert providers["federal_reserve_fomc"]["configured"] is True
    assert providers["databento_market"]["configured"] is False
    assert providers["trading_economics_consensus"]["pit_entitled"] is False
    serialized = json.dumps(payload).lower()
    assert "api_key" not in serialized
    assert "secretstr" not in serialized

    contract = client.get("/v2/data/operation-contract")
    assert contract.status_code == 200
    statuses = contract.json()["statuses"]
    assert statuses["completed"] == {
        "http_status": 200,
        "cli_exit_code": 0,
        "meaning": "The requested operation completed without a known provider failure.",
    }
    assert statuses["partial"]["http_status"] == 207
    assert statuses["partial"]["cli_exit_code"] == 4
    assert statuses["blocked"]["http_status"] == 424
    assert statuses["blocked"]["cli_exit_code"] == 3
    assert contract.json()["authorization_failure_http_status"] == 403


def test_multi_operation_contract_counts_nested_blockers() -> None:
    partial = normalize_multi_operation_result(
        {
            "status": "completed",
            "results": {
                "bls": {"status": "blocked", "records_read": 0},
                "fomc": {"status": "completed", "records_read": 8},
            },
            "failures": {},
        }
    )
    assert partial["status"] == "partial"
    assert partial["blocked_operations"] == {"bls": "blocked"}

    blocked = normalize_multi_operation_result(
        {
            "status": "completed",
            "results": {"bls": {"status": "blocked", "records_read": 0}},
            "failures": {},
        }
    )
    assert blocked["status"] == "blocked"


def test_coverage_keeps_fixture_and_observed_modes_separate(client: TestClient) -> None:
    fixture = client.get("/v2/data/coverage?data_mode=fixture")
    assert fixture.status_code == 200
    fixture_payload = fixture.json()
    assert fixture_payload["data_mode"] == "fixture"
    assert fixture_payload["observed_only"] is False
    assert {item["event_type"] for item in fixture_payload["items"]} == set(DEFAULT_EVENT_TYPES)
    assert all(item["actual"]["data_mode"] == "fixture" for item in fixture_payload["items"])

    observed = client.get("/v2/data/coverage?data_mode=observed")
    assert observed.status_code == 200
    observed_payload = observed.json()
    assert observed_payload["observed_only"] is True
    # Other integration tests may already have persisted observed rows in the
    # session-scoped database.  The isolation contract is that fixture rows can
    # never satisfy an observed coverage query, not that observed rows are absent.
    assert all(
        item["actual"]["data_mode"] in {None, "observed"} for item in observed_payload["items"]
    )


def test_backfill_estimate_and_durable_blocked_job(client: TestClient) -> None:
    query = {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "event_types": "US_CPI,US_NFP,FOMC",
        "assets": ",".join(DEFAULT_ASSETS),
    }
    estimate = client.get("/v2/data/backfill/estimate", params=query)
    assert estimate.status_code == 200
    estimate_payload = estimate.json()
    assert estimate_payload["event_count"] == 32
    assert estimate_payload["asset_count"] == len(DEFAULT_ASSETS)
    assert estimate_payload["estimated_records"] > 0
    assert estimate_payload["allow_execute"] is False
    assert "API key" in estimate_payload["blocked_reason"]
    assert {item["dataset"].split(":")[0] for item in estimate_payload["datasets"]} == {
        "GLBX.MDP3",
        "IFUS.IMPACT",
        "XCBF.PITCH",
    }

    request_payload = {
        "start_date": query["start_date"],
        "end_date": query["end_date"],
        "event_types": query["event_types"].split(","),
        "assets": list(DEFAULT_ASSETS),
        "estimate_id": estimate_payload["estimate_id"],
    }
    started = client.post("/v2/data/backfill", json=request_payload)
    assert started.status_code == 424
    job = started.json()
    assert job["status"] == "blocked"
    assert job["persisted_status"] == "rejected"
    assert job["execution_allowed"] is False

    status = client.get(f"/v2/data/backfill/{job['id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "blocked"
    cancelled = client.post(f"/v2/data/backfill/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "blocked"


@pytest.fixture
def cli_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "cli-v05.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    async def create_schema() -> None:
        engine = create_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())
    monkeypatch.setenv("WORLDSTATE_DATABASE_URL", database_url)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.delenv("TRADING_ECONOMICS_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("WORLDSTATE_ALLOW_PAID_DOWNLOAD", "false")
    return None


def test_cli_doctor_estimate_and_blocked_sync_are_json(
    cli_database: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_health(_settings: Settings) -> list[dict[str, object]]:
        return []

    async def fake_official(
        _engine: object,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
        event_types: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "status": "completed",
            "results": {"range": [start_date, end_date], "event_types": event_types},
            "failures": {},
        }

    async def fake_calendar(
        _engine: object,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        return {
            "status": "completed",
            "results": {"range": [start_date, end_date]},
            "failures": {},
        }

    monkeypatch.setattr("worldstate.api.v2.data_router.provider_health_snapshot", fake_health)
    monkeypatch.setattr("worldstate.cli.sync_official_data", fake_official)
    monkeypatch.setattr("worldstate.cli.run_calendar_sync", fake_calendar)
    assert run(["data-doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["status"] == "ok"
    assert doctor["credentials_exposed"] is False

    assert (
        run(
            [
                "estimate-backfill",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--event-types",
                "US_CPI",
                "--assets",
                "GC,DX",
            ]
        )
        == 0
    )
    estimate = json.loads(capsys.readouterr().out)
    assert estimate["asset_count"] == 2
    assert estimate["allow_execute"] is False

    assert run(["sync-official", "--event-types", "US_CPI"]) == 0
    synced = json.loads(capsys.readouterr().out)
    assert synced["status"] == "completed"
    assert synced["command"] == "sync-official"
    assert synced["requested_event_types"] == ["US_CPI"]
    assert synced["results"]["event_types"] == ["US_CPI"]

    assert run(["sync-calendar", "--start-date", "2025-01-01"]) == 0
    calendar = json.loads(capsys.readouterr().out)
    assert calendar["status"] == "completed"
    assert calendar["command"] == "sync-calendar"


def test_cli_licensed_commands_are_clear_when_unconfigured(
    cli_database: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        run(
            [
                "snapshot-consensus",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-02",
            ]
        )
        == 3
    )
    consensus = json.loads(capsys.readouterr().out)
    assert consensus["status"] == "blocked"
    assert consensus["code"] == "provider_not_configured"

    assert run(["sync-market", "--release-id", str(uuid.uuid4()), "--assets", "GC"]) == 2
    market = json.loads(capsys.readouterr().out)
    assert market["status"] == "error"
    assert market["code"] == "invalid_request"

    assert run(["reconcile-data"]) == 3
    reconciliation = json.loads(capsys.readouterr().out)
    assert reconciliation["status"] == "blocked"
    assert reconciliation["reason"]


def test_cli_official_nested_status_controls_exit_code(
    cli_database: None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_status = "blocked"

    async def fake_official(*_args: object, **_kwargs: object) -> dict[str, object]:
        results: dict[str, object] = {"bls": {"status": child_status}}
        if child_status == "partial":
            results["fred"] = {"status": "completed"}
        return {"status": "completed", "results": results, "failures": {}}

    monkeypatch.setattr("worldstate.cli.sync_official_data", fake_official)
    assert run(["sync-official", "--event-types", "US_CPI"]) == 3
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "blocked"
    assert blocked["blocked_operations"] == {"bls": "blocked"}

    child_status = "partial"
    assert run(["sync-official", "--event-types", "US_CPI"]) == 4
    partial = json.loads(capsys.readouterr().out)
    assert partial["status"] == "partial"
    assert partial["results"]["bls"]["status"] == "partial"


def test_data_sync_api_calls_services_and_surfaces_license_blocks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[date, date]] = []

    async def fake_official(
        _engine: object,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        calls.append((start_date, end_date))
        return {"status": "completed", "results": {"bls": {}}, "failures": {}}

    async def fake_calendar(
        _engine: object,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        return {
            "status": "completed",
            "results": {"range": [start_date, end_date]},
            "failures": {},
        }

    async def fake_reconciliation(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "blocked", "reason": "No persisted comparison is available."}

    monkeypatch.setattr("worldstate.api.v2.data_router.sync_official_data", fake_official)
    monkeypatch.setattr("worldstate.api.v2.data_router.run_calendar_sync", fake_calendar)
    monkeypatch.setattr(
        "worldstate.api.v2.data_router.run_data_reconciliation", fake_reconciliation
    )
    official = client.post(
        "/v2/data/sync/official",
        json={"start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    assert official.status_code == 200
    assert official.json()["status"] == "completed"
    assert calls == [(date(2025, 1, 1), date(2025, 1, 31))]

    calendar = client.post(
        "/v2/data/sync/calendar",
        json={"start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    assert calendar.status_code == 200
    assert calendar.json()["status"] == "completed"

    consensus = client.post(
        "/v2/data/sync/consensus",
        json={"start_date": "2025-01-01", "end_date": "2025-01-02"},
    )
    assert consensus.status_code == 424
    assert consensus.json()["detail"]["status"] == "blocked"
    assert consensus.json()["detail"]["code"] == "provider_not_configured"

    market = client.post(
        "/v2/data/sync/market",
        json={"release_id": str(uuid.uuid4()), "assets": ["GC"]},
    )
    assert market.status_code == 404
    assert market.json()["detail"]["status"] == "error"
    assert market.json()["detail"]["code"] == "invalid_request"

    reconciliation = client.post("/v2/data/reconcile", json={})
    assert reconciliation.status_code == 424
    assert reconciliation.json()["status"] == "blocked"


def test_official_sync_with_no_success_is_blocked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_official(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "status": "completed",
            "results": {
                "bls_calendar": {"status": "blocked"},
                "bls_actuals": {"status": "blocked"},
            },
            "failures": {},
        }

    monkeypatch.setattr("worldstate.api.v2.data_router.sync_official_data", fake_official)
    response = client.post(
        "/v2/data/sync/official",
        json={"start_date": "2025-01-01", "end_date": "2025-01-31"},
    )
    assert response.status_code == 424
    assert response.json()["status"] == "blocked"
    assert response.json()["blocked_operations"] == {
        "bls_calendar": "blocked",
        "bls_actuals": "blocked",
    }


async def test_backfill_uses_provider_metadata_quote_when_key_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'quoted-backfill.db').as_posix()}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    class FakeDatabento:
        calls = 0

        async def estimate_download(self, _request: object) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(
                estimated_records=10,
                estimated_billable_bytes=640,
                estimated_cost_usd=Decimal("0.25"),
                source="provider_metadata",
                confidence="high",
                provider_quoted_at=datetime(2025, 1, 1, tzinfo=UTC),
                uncertainty_notes=(),
            )

        def estimate_cost(self, _request: object) -> SimpleNamespace:
            raise AssertionError("fallback should not be needed")

    fake = FakeDatabento()
    monkeypatch.setattr(
        "worldstate.api.v2.data_router.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=fake),
    )
    settings = Settings(
        database_url=database_url,
        databento_api_key="configured-test-key",
        allow_paid_download=True,
        databento_max_estimated_cost_usd=Decimal("2"),
    )
    payload = BackfillRequestInput(
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        event_types=["US_CPI"],
        assets=["GC", "DX"],
    )
    _, estimate, response = await estimate_backfill_payload(engine, settings, payload)
    assert fake.calls == 4
    assert response["estimation_method"] == "provider_metadata"
    assert response["cost_confidence"] == "medium"
    assert response["estimated_cost_usd"] == 1.0
    assert response["allow_execute"] is True
    assert estimate.estimated_record_count == 40
    await engine.dispose()


async def test_configured_key_with_fallback_quote_cannot_enqueue_paid_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'fallback-quote.db').as_posix()}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    class FallbackDatabento:
        async def estimate_download(self, _request: object) -> SimpleNamespace:
            return SimpleNamespace(
                estimated_records=10,
                estimated_billable_bytes=640,
                estimated_cost_usd=Decimal("0.00001"),
                source="fallback_estimate",
                confidence="low",
                provider_quoted_at=None,
                uncertainty_notes=("metadata quote unavailable",),
            )

        def estimate_cost(self, _request: object) -> SimpleNamespace:
            raise AssertionError("estimate_download already returned its safe fallback")

    monkeypatch.setattr(
        "worldstate.api.v2.data_router.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=FallbackDatabento()),
    )
    settings = Settings(
        database_url=database_url,
        databento_api_key="configured-test-key",
        allow_paid_download=True,
        databento_max_estimated_cost_usd=Decimal("10"),
        scheduler_enabled=False,
    )
    payload = BackfillRequestInput(
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        event_types=["US_CPI"],
        assets=["GC"],
    )
    _, estimate, response = await estimate_backfill_payload(engine, settings, payload)
    assert response["allow_execute"] is False
    assert response["provider_status"] == "configured_quote_unavailable"
    assert "fallback estimates" in str(response["blocked_reason"])
    assert estimate.execution_allowed is False
    await engine.dispose()


def test_backfill_validation_and_unknown_job(client: TestClient) -> None:
    invalid = client.get(
        "/v2/data/backfill/estimate",
        params={
            "start_date": "2025-02-01",
            "end_date": "2025-01-01",
            "event_types": "US_CPI",
            "assets": "GC",
        },
    )
    assert invalid.status_code == 422
    assert client.get(f"/v2/data/backfill/{'0' * 32}").status_code == 404


async def test_existing_backfill_records_match_real_dataset_and_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'coverage-existing.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    t0 = datetime(2025, 1, 15, 13, 30, tzinfo=UTC)
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key="api-existing-cpi-2025-01",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2025-01",
        scheduled_at=t0,
        released_at=t0,
        source_timezone="America/New_York",
        status="released",
        data_version="initial",
        data_mode="observed",
        contamination_level="none",
        clean_window=True,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    instrument = MarketInstrument(
        id=uuid.uuid4(),
        canonical_key="gold_gc_existing_test",
        symbol="GC",
        title="Gold futures",
        asset_class="metals",
        instrument_type="futures",
        exchange="COMEX",
        quote_unit="USD/troy ounce",
        measurement_type="price",
        source_timezone="America/Chicago",
        is_proxy=False,
        proxy_for=None,
        active=True,
        metadata_json={},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all([release, instrument])

    for source_content_hash in ("a" * 64, "b" * 64):
        # A refreshed artifact for the identical event slice must not double-count.
        await record_market_data_manifest(
            engine,
            macro_release_id=release.id,
            release_stage_id=None,
            provider_key="databento",
            dataset="GLBX.MDP3",
            schema_name="ohlcv-1m",
            instrument_id=instrument.id,
            futures_contract_id=None,
            source_symbol="GCG5",
            contract_code="GCG5",
            start_at=t0 - timedelta(minutes=90),
            end_at=t0 + timedelta(minutes=240),
            interval_seconds=60,
            row_count=330,
            size_bytes=26_400,
            contract_selection_rule="highest volume before T0",
            source_content_hash=source_content_hash,
        )

    request = BackfillRequest(
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        event_types=("US_CPI",),
        instruments=("GC",),
        datasets=("ohlcv-1m",),
        dataset_schemas=(("GLBX.MDP3", "ohlcv-1m"),),
        expected_event_count=1,
    )
    estimate = await estimate_backfill(
        engine,
        request,
        budget_limit_usd=Decimal("0"),
        paid_download_allowed=False,
    )
    assert estimate.estimated_record_count == 330
    assert estimate.existing_record_count == 330
    assert estimate.estimated_download_records == 0
    reconciliation = await run_data_reconciliation(engine, release_id=release.id)
    assert reconciliation["status"] == "completed"
    assert reconciliation["market_integrity_checks"] == 2
    await engine.dispose()


async def test_coverage_separates_stored_from_analysis_eligible_and_partial_reconciliation(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'truthful-coverage.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    t0 = datetime(2025, 2, 12, 13, 30, tzinfo=UTC)
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key="truthful-cpi-2025-02",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2025-01",
        scheduled_at=t0,
        released_at=t0,
        source_timezone="America/New_York",
        status="released",
        data_version="initial",
        data_mode="observed",
        contamination_level="none",
        clean_window=True,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    indicators = [
        Indicator(
            id=uuid.uuid4(),
            indicator_key=f"truthful_cpi_{index}",
            name=f"Truthful CPI {index}",
            family="inflation",
            country="USA",
            unit="percent",
            periodicity="monthly",
            description=None,
            hotter_when_higher=True,
            bundle_weight=0.5,
            active=True,
            metadata_json={},
        )
        for index in range(2)
    ]
    quality = DataQualityRecord(
        id=uuid.uuid4(),
        subject_type="release_value",
        subject_id=str(release.id),
        source_name="BLS",
        source_url="https://www.bls.gov/",
        source_type="official",
        acquired_at=t0 + timedelta(minutes=1),
        is_manual=False,
        is_verified=True,
        is_fixture=False,
        is_proxy=False,
        latency_seconds=60,
        granularity_seconds=None,
        missing_reason=None,
        quality_grade="A",
        verification_notes="verified official release",
        metadata_json={},
    )
    values = [
        ReleaseValue(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            release_stage_id=None,
            indicator_id=indicator.id,
            value_kind="actual",
            value=Decimal("3.0") + Decimal(index) / 10,
            raw_value="3.0",
            data_version="initial",
            valid_from=t0,
            captured_at=t0 + timedelta(minutes=1),
            is_initial=True,
            data_mode="observed",
            source_artifact_id=None,
            quality_id=quality.id,
            metadata_json={},
        )
        for index, indicator in enumerate(indicators)
    ]
    unavailable_historical = ReleaseValue(
        id=uuid.uuid4(),
        macro_release_id=release.id,
        release_stage_id=None,
        indicator_id=indicators[0].id,
        value_kind="actual",
        value=Decimal("2.9"),
        raw_value="2.9",
        data_version="historical-current-api",
        valid_from=t0,
        captured_at=t0 + timedelta(days=1),
        is_initial=True,
        data_mode="observed",
        source_artifact_id=None,
        quality_id=quality.id,
        metadata_json={"historical_initial_status": "not_reconstructable_from_current_bls_api"},
    )
    snapshots = [
        ConsensusSnapshot(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            indicator_id=indicators[0].id,
            consensus_value=Decimal("2.9"),
            source_name="Verified manual consensus",
            source_url=None,
            captured_at=t0 - timedelta(minutes=5),
            quality_grade="B",
            is_manual=True,
            data_mode="observed",
            verification_notes="captured before T0",
            source_artifact_id=None,
            quality_id=None,
        ),
        ConsensusSnapshot(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            indicator_id=indicators[1].id,
            consensus_value=Decimal("3.0"),
            source_name="Post-release snapshot",
            source_url=None,
            captured_at=t0 + timedelta(minutes=5),
            quality_grade="A",
            is_manual=False,
            data_mode="observed",
            verification_notes="post release",
            source_artifact_id=None,
            quality_id=None,
        ),
    ]
    instrument = MarketInstrument(
        id=uuid.uuid4(),
        canonical_key="truthful_gold_gc",
        symbol="GC",
        title="Gold futures",
        asset_class="metals",
        instrument_type="futures",
        exchange="COMEX",
        quote_unit="USD/troy ounce",
        measurement_type="price",
        source_timezone="America/Chicago",
        is_proxy=False,
        proxy_for=None,
        active=True,
        metadata_json={},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all(
            [release, *indicators, quality, *values, unavailable_historical, *snapshots, instrument]
        )
    manifest = await record_market_data_manifest(
        engine,
        macro_release_id=release.id,
        release_stage_id=None,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=None,
        source_symbol="GCG5",
        contract_code="GCG5",
        start_at=t0 - timedelta(minutes=90),
        end_at=t0 + timedelta(minutes=240),
        interval_seconds=60,
        row_count=10,
        size_bytes=800,
        quality_grade="A",
        source_content_hash="c" * 64,
    )
    unqualified_manifest = await record_market_data_manifest(
        engine,
        macro_release_id=release.id,
        release_stage_id=None,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=None,
        source_symbol="GCJ5",
        contract_code="GCJ5",
        start_at=t0 - timedelta(minutes=90),
        end_at=t0 + timedelta(minutes=240),
        interval_seconds=60,
        row_count=5,
        size_bytes=400,
        quality_grade="D",
        source_content_hash="e" * 64,
    )
    await record_market_reconciliation(
        engine,
        subject_id=str(manifest.id),
        provider_key="databento",
        checks={"bars_present": True, "ohlc_valid": True},
    )
    await reconcile_values(
        engine,
        subject_type="release_value",
        subject_id=str(values[0].id),
        field_name="actual",
        authoritative_provider_key="bls_official",
        comparison_provider_key="trading_economics",
        authoritative_value=values[0].value,
        comparison_value=values[0].value,
        unit="percent",
    )

    coverage = await build_data_coverage(engine, data_mode="observed")
    cpi = next(item for item in coverage["items"] if item["event_type"] == "US_CPI")
    assert cpi["actual"]["stored_record_count"] == 3
    assert cpi["actual"]["analysis_eligible_record_count"] == 2
    assert cpi["consensus"]["stored_record_count"] == 2
    assert cpi["consensus"]["analysis_eligible_record_count"] == 1
    assert cpi["intraday"]["stored_record_count"] == 15
    assert cpi["intraday"]["analysis_eligible_record_count"] == 10
    assert cpi["source_quality"] == "B"
    assert cpi["source_quality"] != "UNKNOWN"

    async with factory() as session:
        provenance = await _release_data_provenance(session, release, None, None)
    assert provenance["reconciled"] is False
    assert provenance["reconciliation_status"] == "partial"
    reconciliation_summary = cast(dict[str, Any], provenance["reconciliation_summary"])
    assert reconciliation_summary["expected_subject_count"] == 4
    assert reconciliation_summary["covered_subject_count"] == 2
    assert set(reconciliation_summary["missing_subject_ids"]) == {
        str(values[1].id),
        str(unqualified_manifest.id),
    }
    assert reconciliation_summary["partial_comparisons_are_complete"] is False

    await reconcile_values(
        engine,
        subject_type="release_value",
        subject_id=str(values[1].id),
        field_name="actual",
        authoritative_provider_key="bls_official",
        comparison_provider_key="trading_economics",
        authoritative_value=values[1].value,
        comparison_value=values[1].value,
        unit="percent",
    )
    await record_market_reconciliation(
        engine,
        subject_id=str(unqualified_manifest.id),
        provider_key="databento",
        checks={"bars_present": True, "ohlc_valid": True},
    )
    await reconcile_values(
        engine,
        subject_type="macro_release",
        subject_id=str(release.id),
        field_name="truthful_cpi_0.release_time",
        authoritative_provider_key="bls_official",
        comparison_provider_key="trading_economics",
        authoritative_value=Decimal("1"),
        comparison_value=Decimal("2"),
        unit="unix_seconds",
    )
    async with factory() as session:
        attention = await _release_data_provenance(session, release, None, None)
    assert attention["reconciled"] is False
    assert attention["reconciliation_status"] == "attention_required"
    attention_summary = cast(dict[str, Any], attention["reconciliation_summary"])
    assert attention_summary["missing_subject_ids"] == []
    await engine.dispose()


async def test_provider_status_includes_fred_observation_range_and_next_snapshot(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'provider-range.db').as_posix()}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime.now(UTC)
    provider = Provider(
        key="fred_alfred",
        name="FRED / ALFRED",
        base_url="https://api.stlouisfed.org/",
        enabled=True,
        requires_credentials=True,
        terms_url="https://fred.stlouisfed.org/docs/api/terms_of_use.html",
    )
    entity = EconomicEntity(
        iso2="US",
        iso3="USA",
        name="United States",
        entity_type="country",
        parent_id=None,
        currency="USD",
        timezone="America/New_York",
        latitude=None,
        longitude=None,
        metadata_json={},
    )
    series = Series(
        id=uuid.uuid4(),
        provider_id=0,
        native_id="DGS10",
        canonical_key="provider-range-dgs10",
        entity_id=0,
        title="10-Year Treasury Rate",
        description=None,
        frequency="daily",
        unit="percent",
        seasonal_adjustment=None,
        observation_type="rate",
        source_url="https://fred.stlouisfed.org/series/DGS10",
        release_key=None,
        availability_method="provider_timestamp",
        availability_precision="day",
        default_transform="level",
        active=True,
        metadata_json={},
    )
    job = SyncJob(
        id=uuid.uuid4(),
        job_key="provider-range-consensus",
        provider_key="trading_economics",
        operation="snapshot_consensus",
        schedule_type="release_relative",
        schedule_json={"offset_minutes": [-5]},
        enabled=True,
        data_mode="observed",
        max_attempts=3,
        retry_backoff_seconds=60,
        timeout_seconds=300,
        last_scheduled_at=None,
        next_run_at=None,
        config_json={},
    )
    next_snapshot = now + timedelta(hours=2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all([provider, entity])
        await session.flush()
        series.provider_id = provider.id
        series.entity_id = entity.id
        session.add_all([series, job])
        await session.flush()
        session.add(
            Observation(
                series_id=series.id,
                period_start=date(2024, 1, 2),
                period_end=date(2024, 1, 2),
                value=Decimal("4.0"),
                raw_value="4.0",
                vintage_date=date(2024, 1, 3),
                realtime_start=date(2024, 1, 3),
                realtime_end=None,
                available_at=datetime(2024, 1, 3, tzinfo=UTC),
                availability_method="provider_timestamp",
                availability_precision="day",
                fetched_at=now,
                is_preliminary=False,
                is_revised=False,
                data_mode="observed",
                quality_flags=[],
                source_hash="d" * 64,
            )
        )
        session.add(
            Observation(
                series_id=series.id,
                period_start=date(2010, 1, 2),
                period_end=date(2010, 1, 2),
                value=Decimal("9.9"),
                raw_value="9.9",
                vintage_date=date(2010, 1, 3),
                realtime_start=date(2010, 1, 3),
                realtime_end=None,
                available_at=datetime(2010, 1, 3, tzinfo=UTC),
                availability_method="provider_timestamp",
                availability_precision="day",
                fetched_at=now,
                is_preliminary=False,
                is_revised=False,
                data_mode="fixture",
                quality_flags=["legacy_demo"],
                source_hash="f" * 64,
            )
        )
        session.add(
            SyncJobRun(
                id=uuid.uuid4(),
                sync_job_id=job.id,
                provider_run_id=None,
                source_artifact_id=None,
                retry_of_id=None,
                idempotency_key="provider-range-next-snapshot",
                status="pending",
                data_mode="observed",
                attempt=1,
                scheduled_for=next_snapshot,
                available_at=next_snapshot,
                started_at=None,
                heartbeat_at=None,
                completed_at=None,
                records_read=0,
                records_written=0,
                checkpoint_json={},
                input_json={},
                output_json={},
                error_type=None,
                error_message=None,
            )
        )
    status = await build_provider_status(engine, Settings(database_url=database_url))
    providers = {item["provider_id"]: item for item in status["items"]}
    assert providers["fred_alfred"]["data_range"] == {
        "start": date(2024, 1, 2),
        "end": date(2024, 1, 2),
    }
    assert providers["trading_economics_consensus"]["next_planned_snapshot"] == next_snapshot
    async with factory() as session:
        observed_context = await _pre_event_regime_context(
            session,
            datetime(2025, 1, 1, tzinfo=UTC),
            data_mode="observed",
        )
        fixture_context = await _pre_event_regime_context(
            session,
            datetime(2025, 1, 1, tzinfo=UTC),
            data_mode="fixture",
        )
    assert observed_context["ten_year_yield"] == 4.0
    assert fixture_context["ten_year_yield"] == 9.9
    await engine.dispose()
