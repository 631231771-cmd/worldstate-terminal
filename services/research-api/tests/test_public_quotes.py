from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from worldstate.application.quote_service import QuoteService
from worldstate.provider_kit.public_quotes import empty_quotes, parse_quote


def test_yield_change_is_basis_points_not_price_percent() -> None:
    now = datetime.now(UTC)
    spec = next(q for q in empty_quotes() if q.symbol == "^TNX")
    result = parse_quote(spec, {"chart": {"result": [{
        "meta": {"symbol": "^TNX", "regularMarketPrice": 4.95,
                 "regularMarketTime": now.timestamp(), "previousClose": 5.0},
        "timestamp": [now.timestamp()], "indicators": {"quote": [{"close": [4.95]}]},
    }]}}, now)
    assert result.change == pytest.approx(-5)
    assert result.change_unit == "bp"
    assert result.status == "delayed"
    assert not result.event_research_eligible


def test_spot_identity_and_time_are_verified() -> None:
    now = datetime.now(UTC)
    payload = {"symbol": "XAU", "price": 4000, "updatedAt": now.isoformat()}
    result = parse_quote(empty_quotes()[0], payload, now)
    assert result.status == "indicative"
    assert result.previous_close is None
    for bad in [dict(payload, symbol="XAG"), dict(payload, price=float("nan")),
                dict(payload, updatedAt=(now + timedelta(hours=1)).isoformat())]:
        with pytest.raises(ValueError, match=r"identity|non-finite|timestamp"):
            parse_quote(empty_quotes()[0], bad, now)


async def test_cache_bounds_calls_and_preserves_timestamp_on_failure() -> None:
    service = QuoteService()
    now = datetime.now(UTC)
    good = parse_quote(empty_quotes()[0], {
        "symbol": "XAU", "price": 4000, "updatedAt": now.isoformat(),
    }, now)
    with patch("worldstate.application.quote_service.fetch_quote", new_callable=AsyncMock) as fetch:
        fetch.return_value = good
        await service.read()
        await service.read()
        assert fetch.call_count == len(empty_quotes())
        service.next_refresh = 0
        fetch.side_effect = ValueError("offline")
        response = await service.read()
    assert response.items[0].price == 4000
    assert response.items[0].quoted_at == now
    assert response.items[0].status == "stale"
    assert response.items[0].error
