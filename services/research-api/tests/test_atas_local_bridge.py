"""GC bridge is opt-in, ephemeral, loopback-only, and display-only."""

import json
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from worldstate.api.v2.product_router import bridge_peer_allowed
from worldstate.application.live_quote_service import LiveQuoteService
from worldstate.provider_kit.atas_local import AtasChartSnapshot


def payload(contract: str = "GCZ6") -> dict[str, object]:
    now = datetime.now(UTC)
    start = now.replace(second=0, microsecond=0)
    return {
        "schema_version": 1, "symbol": "GC", "contract": contract,
        "source_symbol": contract, "exchange": "COMEX",
        "event_timestamp": now.isoformat(), "last_trade_timestamp": now.isoformat(),
        "last_trade": 3600.5, "best_bid": 3600.4, "best_ask": 3600.6,
        "last_trade_volume": 3,
        "bar_1m": {"start": start.isoformat(), "open": 3600, "high": 3601,
                   "low": 3599, "close": 3600.5, "volume": 22},
    }


def test_loopback_and_opt_in_policy(client: TestClient) -> None:
    assert not bridge_peer_allowed("127.0.0.1", None, False)
    assert bridge_peer_allowed("127.0.0.1", None, True)
    assert not bridge_peer_allowed("192.168.1.2", None, True)
    assert not bridge_peer_allowed("127.0.0.1", "http://evil.example", True)
    response = client.get("/v2/product/live-gc")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False, "connected": False, "last_seen_at": None, "quote": None,
    }
    with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
        "/v2/product/local-bridge/gc",
    ):
        pass
    assert rejected.value.code == 1008


def test_websocket_end_to_end_loopback_only(client: TestClient) -> None:
    service: LiveQuoteService = cast(FastAPI, client.app).state.live_quote_service
    service.enabled = True
    loopback_client = TestClient(client.app, client=("127.0.0.1", 50000))
    try:
        with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect(
            "/v2/product/local-bridge/gc",
        ):
            pass
        assert rejected.value.code == 1008
        with (
            pytest.raises(WebSocketDisconnect) as rejected_origin,
            loopback_client.websocket_connect(
                "/v2/product/local-bridge/gc", headers={"Origin": "http://evil.example"},
            ),
        ):
            pass
        assert rejected_origin.value.code == 1008
        with loopback_client.websocket_connect("/v2/product/local-bridge/gc") as socket:
            socket.send_text(json.dumps(payload()))
            # TestClient bridge handler runs concurrently with the next read.
            response = loopback_client.get("/v2/product/live-gc")
            assert response.status_code == 200
            assert response.json()["connected"]
            assert response.json()["quote"]["symbol"] == "GCZ6"
            assert not response.json()["quote"]["event_research_eligible"]
            root_only = payload()
            root_only["contract"] = None
            root_only["source_symbol"] = "GC"
            socket.send_text(json.dumps(root_only))
            response = loopback_client.get("/v2/product/live-gc")
            assert response.json()["quote"]["symbol"] == "GC"
            assert response.json()["quote"]["contract_code"] is None
            assert not response.json()["quote"]["event_research_eligible"]
        assert not loopback_client.get("/v2/product/live-gc").json()["connected"]
    finally:
        service.enabled = False


def test_reject_ambiguous_and_non_gc_contracts() -> None:
    for contract in ("GC=F", "GC", "CLZ6", "GC.continuous", "GCZ6@COMEX"):
        with pytest.raises(ValidationError, match="specific GC chart contract"):
            AtasChartSnapshot.model_validate(payload(contract))
    bad = payload()
    bad["best_bid"] = 3601
    with pytest.raises(ValidationError, match="crossed bid/ask"):
        AtasChartSnapshot.model_validate(bad)
    continuous_chart = payload()
    continuous_chart["source_symbol"] = "#GCZ6"
    assert AtasChartSnapshot.model_validate(continuous_chart).contract == "GCZ6"
    wrong_source = payload()
    wrong_source["source_symbol"] = "#GCG7"
    with pytest.raises(ValidationError, match="source symbol"):
        AtasChartSnapshot.model_validate(wrong_source)
    unverified = payload()
    unverified["contract"] = None
    unverified["source_symbol"] = "GC"
    assert AtasChartSnapshot.model_validate(unverified).contract is None
    unverified["source_symbol"] = "#GCZ6"
    with pytest.raises(ValidationError, match="retain its GC root"):
        AtasChartSnapshot.model_validate(unverified)


async def test_live_quote_normalizes_without_research_eligibility() -> None:
    service = LiveQuoteService(enabled=True)
    connection = await service.connect()
    with pytest.raises(ValueError, match="already connected"):
        await service.connect()
    await service.ingest(connection, AtasChartSnapshot.model_validate(payload()))
    result = await service.read()
    assert result.enabled
    assert result.connected
    assert result.quote is not None
    assert result.quote.status == "live"
    assert result.quote.symbol == "GCZ6"
    assert result.quote.provider == "atas_local_bridge"
    assert result.quote.best_bid == 3600.4
    assert result.quote.bar_1m is not None
    assert result.quote.bar_1m.volume == 22
    assert len(result.quote.points) == 1
    assert not result.quote.event_research_eligible
    await service.disconnect(connection)
    disconnected = await service.read()
    assert not disconnected.connected
    assert disconnected.quote is not None
    assert disconnected.quote.status == "stale"


async def test_reject_replayed_snapshot_and_isolate_contract_change() -> None:
    service = LiveQuoteService(enabled=True)
    connection = await service.connect()
    old = payload()
    old_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    old["event_timestamp"] = old_at
    old["last_trade_timestamp"] = old_at
    old["bar_1m"] = None
    with pytest.raises(ValueError, match="not current"):
        await service.ingest(connection, AtasChartSnapshot.model_validate(old))
    await service.ingest(connection, AtasChartSnapshot.model_validate(payload()))
    await service.ingest(connection, AtasChartSnapshot.model_validate(payload("GCG7")))
    result = await service.read()
    assert result.quote is not None
    assert result.quote.symbol == "GCG7"
    assert len(result.quote.points) == 1  # no spliced contract history


async def test_undated_sdk_identity_stays_unverified_and_display_only() -> None:
    service = LiveQuoteService(enabled=True)
    connection = await service.connect()
    raw = payload()
    raw["contract"] = None
    raw["source_symbol"] = "GC"
    await service.ingest(connection, AtasChartSnapshot.model_validate(raw))
    result = await service.read()
    assert result.connected
    assert result.quote is not None
    assert result.quote.status == "live"
    assert result.quote.symbol == "GC"
    assert result.quote.contract_code is None
    assert result.quote.source_symbol == "GC"
    assert "月份未核验" in result.quote.label
    assert not result.quote.event_research_eligible
