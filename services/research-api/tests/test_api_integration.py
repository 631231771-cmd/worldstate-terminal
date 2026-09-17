from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient


def test_api_v2_bootstraps_complete_vertical_slice(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    assert {"US_CPI", "US_NFP", "FOMC"} <= set(release_index)
    assert client.get("/v1/health").status_code == 404

    health = client.get("/v2/health")
    assert health.status_code == 200
    assert health.json()["api_version"] == "v2"

    for release_type in ("US_CPI", "US_NFP", "FOMC"):
        release_id = str(release_index[release_type]["id"])
        for suffix in (
            "",
            "/stages",
            "/values",
            "/consensus",
            "/windows",
            "/timeline",
            "/reactions",
            "/cross-asset",
            "/historical-matches",
            "/explanations",
            "/hypotheses",
            "/report",
            "/evidence-pack",
        ):
            response = client.get(f"/v2/releases/{release_id}{suffix}")
            assert response.status_code == 200, (release_type, suffix, response.text)

    for path in (
        "/v2/today",
        "/v2/calendar",
        "/v2/releases",
        "/v2/providers",
        "/v2/provider-runs",
        "/v2/regime",
        "/v2/regimes",
        "/v2/methods",
    ):
        assert client.get(path).status_code == 200, path


def test_today_only_exposes_qualified_research_for_requested_mode(
    client: TestClient,
) -> None:
    observed = client.get("/v2/today?data_mode=observed").json()
    assert all(item["data_mode"] == "observed" for item in observed["latest_research"])
    assert all(item["status"] == "released" for item in observed["latest_research"])
    assert all(item["analysis_status"] == "completed" for item in observed["latest_research"])
    assert all(item["reproducibility_status"] == "complete" for item in observed["latest_research"])
    fixture = client.get("/v2/today?data_mode=fixture").json()
    assert all(item["data_mode"] == "fixture" for item in fixture["latest_research"])
    assert all(item["status"] == "released" for item in fixture["latest_research"])


def test_regime_respects_data_mode_and_does_not_fall_back_to_fixture(
    client: TestClient,
) -> None:
    observed = client.get("/v2/regime?data_mode=observed").json()
    assert observed["state"] == "unavailable"
    assert observed["data_mode"] == "observed"
    fixture = client.get("/v2/regimes?data_mode=fixture").json()
    assert fixture["state"] == "ready"
    assert fixture["data_mode"] == "fixture"


def test_cpi_research_is_evidence_bounded(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    release_id = str(release_index["US_CPI"]["id"])
    detail = client.get(f"/v2/releases/{release_id}").json()
    historical = client.get(f"/v2/releases/{release_id}/historical-matches").json()
    evidence = client.get(f"/v2/releases/{release_id}/evidence-pack").json()
    assistant = client.post(
        "/v2/research/assistant",
        json={"release_id": release_id, "question": "黄金为什么这样反应？"},
    ).json()

    assert detail["bundle"]["classification"]
    assert {"headline_mom", "headline_yoy", "core_mom", "core_yoy"} <= set(detail["values"])
    assert historical["filter_recipe"] == "macro-history-v0.5-mode-isolated"
    assert historical["pre_filter_count"] >= historical["post_filter_count"]
    if historical["post_filter_count"] < 15:
        assert all(
            metric.get("probability_suppressed") is True
            for metric in historical["metrics"].values()
        )
    assert evidence["schema_version"] == "evidence-pack-v1"
    assert evidence["constraints"]["no_unique_causality_claim"] is True
    assert assistant["mode"] == "deterministic"
    assert assistant["validation"]["valid"] is True
    for heading in ("已确认事实", "历史关系", "当前推断", "竞争性解释", "无法确认"):
        assert heading in assistant["answer"]


def test_nfp_revision_and_fomc_stage_repricing(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    nfp_id = str(release_index["US_NFP"]["id"])
    nfp = client.get(f"/v2/releases/{nfp_id}").json()
    assert nfp["bundle"]["revision_dominant"] is False
    assert nfp["bundle"]["revision_analysis"]["method"] == "weighted_per_indicator_standardization"
    assert nfp["bundle"]["classification"] != "主要变化来自前值修正"

    fomc_id = str(release_index["FOMC"]["id"])
    rerun = client.post(f"/v2/releases/{fomc_id}/analysis-runs")
    assert rerun.status_code == 200
    timeline = client.get(f"/v2/releases/{fomc_id}/timeline").json()
    windows = client.get(f"/v2/releases/{fomc_id}/windows").json()
    stage_keys = [stage["key"] for stage in timeline["stages"]]
    assert stage_keys == ["statement", "press_conference", "key_qa", "press_end"]

    gold_post5 = {
        (item["stage_key"], item["instrument_key"]): item
        for item in windows["items"]
        if item["window_key"] == "post_5m"
    }
    statement = gold_post5[("statement", "gold_gc")]
    press = gold_post5[("press_conference", "gold_gc")]
    assert statement["return_percent"] > 0
    assert press["return_percent"] < 0
    assert press["direction_reversal"] is True


def test_quality_proxy_and_methodology_are_explicit(client: TestClient) -> None:
    instruments = client.get("/v2/instruments").json()
    proxies = [item for item in instruments if item["is_proxy"]]
    assert proxies
    assert all(item["proxy_for"] for item in proxies)

    quality = client.get("/v2/data-quality").json()
    assert quality["fixture_records"] > 0
    methodology = client.get("/v2/methodology").json()
    assert methodology["historical_sample_policy"]["probability_minimum"] == 15
    assert "No unique deterministic cause" in methodology["causality_policy"]


def test_manual_release_consensus_csv_and_analysis_workflow(client: TestClient) -> None:
    release_payload = {
        "release_key": "test-us-cpi-2030-01",
        "release_type": "US_CPI",
        "title": "测试用美国CPI",
        "period_label": "2030-01",
        "scheduled_at": "2030-02-13T13:30:00Z",
        "released_at": "2030-02-13T13:30:00Z",
        "source_name": "Test source",
        "source_url": "https://example.test/cpi",
        "verified": True,
        "values": {
            "headline_mom": {"actual": 0.4, "previous": 0.3, "revised_previous": 0.3},
            "headline_yoy": {"actual": 3.2, "previous": 3.1, "revised_previous": 3.1},
            "core_mom": {"actual": 0.3, "previous": 0.2, "revised_previous": 0.2},
            "core_yoy": {"actual": 3.4, "previous": 3.3, "revised_previous": 3.3},
        },
    }
    created = client.post("/v2/releases", json=release_payload)
    assert created.status_code == 200, created.text
    release_id = created.json()["release_id"]

    # A valid observed release is visible before its first AnalysisRun.  Research
    # projections must disclose the missing run instead of making Event Lab fail
    # with a misleading "macro release not found" response.
    pending_history = client.get(f"/v2/releases/{release_id}/historical-matches")
    pending_explanations = client.get(f"/v2/releases/{release_id}/explanations")
    assert pending_history.status_code == 200
    assert pending_history.json()["analysis_run_id"] is None
    assert pending_history.json()["mode"] == "not_analyzed"
    assert pending_explanations.status_code == 200
    assert pending_explanations.json()["analysis_run_id"] is None
    assert pending_explanations.json()["confidence"] == 0.0
    assert pending_explanations.json()["data_gaps"]

    for indicator_key, value in {
        "headline_mom": 0.3,
        "headline_yoy": 3.1,
        "core_mom": 0.2,
        "core_yoy": 3.3,
    }.items():
        consensus = client.post(
            f"/v2/releases/{release_id}/consensus",
            json={
                "indicator_key": indicator_key,
                "consensus_value": value,
                "source_name": "Manual test consensus",
                "source_url": "https://example.test/consensus",
                "captured_at": "2030-02-13T12:00:00Z",
                "quality_grade": "B",
                "is_manual": True,
                "verification_notes": "Test-only point-in-time snapshot",
            },
        )
        assert consensus.status_code == 200, consensus.text

    late_consensus = client.post(
        f"/v2/releases/{release_id}/consensus",
        json={
            "indicator_key": "headline_mom",
            "consensus_value": 0.3,
            "source_name": "Late source",
            "captured_at": "2030-02-13T14:00:00Z",
        },
    )
    assert late_consensus.status_code == 400

    csv_rows = ["timestamp,instrument_key,open,high,low,close,volume"]
    for index in range(76):
        timestamp = datetime.fromisoformat("2030-02-13T13:15:00+00:00") + timedelta(minutes=index)
        close = 2000 - index / 10
        csv_rows.append(
            f"{timestamp.isoformat()},gold_gc,{close},{close + 1},{close - 1},{close},100"
        )
    csv_text = "\n".join(csv_rows)
    preview = client.post(
        f"/v2/releases/{release_id}/market-bars/preview",
        json={
            "instrument_key": "gold_gc",
            "csv_text": csv_text,
            "provider_key": "test_csv",
            "source_name": "Test CSV",
            "verified": True,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["eligibility"]["status"] == "eligible"
    imported = client.post(
        f"/v2/releases/{release_id}/market-bars/import",
        json={
            "instrument_key": "gold_gc",
            "csv_text": csv_text,
            "provider_key": "test_csv",
            "source_name": "Test CSV",
            "verified": True,
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["inserted"] == 76
    assert imported.json()["eligibility"]["eligible"] is True

    analyzed = client.post(f"/v2/releases/{release_id}/analysis-runs")
    assert analyzed.status_code == 200, analyzed.text
    detail = client.get(f"/v2/releases/{release_id}").json()
    assert detail["bundle"]["classification"] == "全面偏热"
    assert detail["latest_analysis"]["status"] == "completed"


def test_observed_context_market_csv_is_separate_from_event_windows(client: TestClient) -> None:
    csv_text = "\n".join(
        [
            "timestamp,instrument_key,open,high,low,close,volume",
            "2030-01-01T00:00:00Z,gold_gc,2000,2010,1990,2005,100",
            "2030-01-02T00:00:00Z,gold_gc,2005,2020,2000,2015,110",
        ]
    )
    imported = client.post(
        "/v2/market-bars/import-context",
        json={
            "instrument_key": "gold_gc",
            "csv_text": csv_text,
            "provider_key": "manual_context_test",
            "source_name": "Verified daily context test",
            "source_url": "https://example.test/daily-bars",
            "verified": True,
            "interval_seconds": 86400,
        },
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["inserted"] == 2
    assert body["data_mode"] == "observed"
    assert body["context_only"] is True
    assert body["not_event_window"] is True
    repeated = client.post(
        "/v2/market-bars/import-context",
        json={
            "instrument_key": "gold_gc",
            "csv_text": csv_text,
            "provider_key": "manual_context_test",
            "source_name": "Verified daily context test",
            "verified": True,
            "interval_seconds": 86400,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True


def test_official_macro_csv_import_keeps_manual_provenance_and_pit_boundary(
    client: TestClient,
) -> None:
    csv_text = "\n".join(
        [
            "canonical_key,native_id,title,entity_iso3,frequency,unit,period_start,value,vintage_date,available_at",
            "JPN.GROWTH.INDPRO,boj.demo,Japan industrial production,JPN,monthly,index,"
            "2026-06-01,101.2,2026-07-31,2026-07-31T00:30:00Z",
            "CHN.GROWTH.RETAIL,china.demo,China retail sales,CHN,monthly,percent,"
            "2026-06-01,4.8,2026-07-15,2026-07-15T02:00:00Z",
        ]
    )
    imported = client.post(
        "/v2/data/macro-series/import-official-csv",
        json={
            "csv_text": csv_text,
            "provider_key": "manual_official_test",
            "source_name": "Official Japan China export",
            "source_url": "https://example.gov/official-export.csv",
            "verified": True,
        },
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["inserted"] == 2
    assert body["manual"] is True
    assert body["point_in_time"] is True
    assert set(body["series"]) == {"JPN.GROWTH.INDPRO", "CHN.GROWTH.RETAIL"}

    repeated = client.post(
        "/v2/data/macro-series/import-official-csv",
        json={
            "csv_text": csv_text,
            "provider_key": "manual_official_test",
            "source_name": "Official Japan China export",
            "source_url": "https://example.gov/official-export.csv",
            "verified": True,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True


def test_official_macro_csv_requires_traceable_source(client: TestClient) -> None:
    response = client.post(
        "/v2/data/macro-series/import-official-csv",
        json={
            "csv_text": (
                "canonical_key,period_start,value,entity_iso3\nJPN.GROWTH.X,2026-01-01,1,JPN"
            ),
            "source_name": "unlinked file",
            "source_url": "",
        },
    )
    assert response.status_code == 422


def test_consensus_csv_import_keeps_pre_t0_and_manual_provenance(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    release = release_index["US_CPI"]
    scheduled = datetime.fromisoformat(str(release["scheduled_at"]))
    csv_text = "\n".join(
        [
            "indicator_key,consensus_value,captured_at,source_name,source_url,quality_grade",
            f"headline_mom,0.2,{(scheduled - timedelta(minutes=20)).isoformat()},Manual CSV,https://example.test/csv,B",
        ]
    )
    preview_text = "\n".join(
        [
            "indicator_key,consensus_value,captured_at,source_name",
            f"headline_mom,0.2,{(scheduled - timedelta(minutes=20)).isoformat()},Manual CSV",
            f"core_mom,0.3,{(scheduled + timedelta(minutes=5)).isoformat()},Late reference",
            f"unknown_key,1,{(scheduled - timedelta(minutes=20)).isoformat()},Unknown",
        ]
    )
    preview = client.post(
        f"/v2/releases/{release['id']}/consensus/import-csv/preview",
        json={"csv_text": preview_text},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"] == {
        "eligible": 1,
        "post_t0": 1,
        "unknown_indicator": 1,
        "invalid": 0,
        "total": 3,
    }
    response = client.post(
        f"/v2/releases/{release['id']}/consensus/import-csv",
        json={"csv_text": csv_text},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inserted"] == 1
    assert body["is_manual"] is True
    assert body["point_in_time"] is True

    late = "\n".join(
        [
            "indicator_key,consensus_value,captured_at",
            f"headline_mom,0.2,{(scheduled + timedelta(minutes=5)).isoformat()}",
        ]
    )
    rejected = client.post(
        f"/v2/releases/{release['id']}/consensus/import-csv",
        json={"csv_text": late},
    )
    assert rejected.status_code == 400


def test_analysis_run_is_replayable_idempotent_and_evidence_bound(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    release_id = str(release_index["US_CPI"]["id"])
    first = client.post(
        f"/v2/releases/{release_id}/analysis-runs",
        headers={"Idempotency-Key": "cpi-stability-test"},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["analysis_run_id"]
    repeated = client.post(
        f"/v2/releases/{release_id}/analysis-runs",
        headers={"Idempotency-Key": "cpi-stability-test"},
    )
    assert repeated.json()["analysis_run_id"] == first_id

    same_input_id = client.post(f"/v2/releases/{release_id}/analysis-runs?force=true").json()[
        "analysis_run_id"
    ]

    manifest = client.get(f"/v2/analysis-runs/{first_id}/manifest")
    replay = client.post(f"/v2/analysis-runs/{first_id}/replay")
    claims = client.get(f"/v2/analysis-runs/{first_id}/claims").json()["items"]
    evidence = client.get(f"/v2/analysis-runs/{first_id}/evidence").json()["items"]
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["reproducibility_status"] == "complete"
    assert all(
        body[key]
        for key in (
            "input_snapshot_hash",
            "config_hash",
            "output_hash",
            "market_dataset_hash",
            "historical_sample_hash",
        )
    )
    assert body["release_value_ids"]
    assert body["consensus_snapshot_ids"]
    assert body["release_stage_ids"]
    same_manifest = client.get(f"/v2/analysis-runs/{same_input_id}/manifest").json()
    assert same_manifest["input_snapshot_hash"] == body["input_snapshot_hash"]
    assert same_manifest["config_hash"] == body["config_hash"]
    assert same_manifest["output_hash"] == body["output_hash"]
    assert replay.json()["replayed"] is True
    assert replay.json()["replayed_output_hash"] == body["output_hash"]
    evidence_ids = {item["evidence_id"] for item in evidence}
    assert claims
    assert all(set(item["evidence_ids"]) <= evidence_ids for item in claims)
    assert all(item["evidence_ids"] for item in claims if item["claim_type"] == "confirmed_fact")


def test_consensus_and_market_mutations_change_new_run_hashes(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    release_id = str(release_index["US_CPI"]["id"])
    detail = client.get(f"/v2/releases/{release_id}").json()
    old_run_id = detail["latest_analysis"]["id"]
    old_manifest = client.get(f"/v2/analysis-runs/{old_run_id}/manifest").json()
    scheduled_at = datetime.fromisoformat(detail["scheduled_at"])
    captured_at = (scheduled_at - timedelta(minutes=45)).isoformat()
    old_consensus = float(detail["values"]["headline_mom"]["consensus"])
    captured = client.post(
        f"/v2/releases/{release_id}/consensus",
        json={
            "indicator_key": "headline_mom",
            "consensus_value": old_consensus + 0.01,
            "source_name": "Hash mutation test",
            "captured_at": captured_at,
            "quality_grade": "C",
            "is_manual": True,
            "verification_notes": "Deliberate test snapshot",
        },
    )
    assert captured.status_code == 200, captured.text
    consensus_run = client.post(f"/v2/releases/{release_id}/analysis-runs?force=true").json()[
        "analysis_run_id"
    ]
    consensus_manifest = client.get(f"/v2/analysis-runs/{consensus_run}/manifest").json()
    assert consensus_manifest["input_snapshot_hash"] != old_manifest["input_snapshot_hash"]

    released_at = datetime.fromisoformat(detail["released_at"])
    csv_rows = ["timestamp,instrument_key,open,high,low,close,volume"]
    for index in range(301):
        timestamp = released_at - timedelta(minutes=60) + timedelta(minutes=index)
        close = 2370 + index / 100
        csv_rows.append(
            f"{timestamp.isoformat()},gold_gc,{close},{close + 1},{close - 1},{close},1"
        )
    csv_text = "\n".join(csv_rows)
    imported = client.post(
        f"/v2/releases/{release_id}/market-bars/import",
        json={
            "instrument_key": "gold_gc",
            "csv_text": csv_text,
            "provider_key": "hash_mutation_test",
            "source_name": "Hash mutation test",
            "verified": True,
            "is_fixture": True,
        },
    )
    assert imported.status_code == 200, imported.text
    market_run = client.post(f"/v2/releases/{release_id}/analysis-runs?force=true").json()[
        "analysis_run_id"
    ]
    market_manifest = client.get(f"/v2/analysis-runs/{market_run}/manifest").json()
    assert market_manifest["market_dataset_hash"] != consensus_manifest["market_dataset_hash"]
    assert market_manifest["input_snapshot_hash"] != consensus_manifest["input_snapshot_hash"]
    assert client.post(f"/v2/analysis-runs/{old_run_id}/replay").json()["replayed"] is True
