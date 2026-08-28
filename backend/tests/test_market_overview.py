"""
The global block of the market overview payload.

Narrow on purpose: this covers the dominance readings the Home ribbon and the
Overview stats bar draw, and specifically that stablecoin share is carried
through. CoinGecko has always returned it under `market_cap_percentage.usdt`; it
was simply never read, and the bar it feeds is the one figure on that ribbon
that says something about intent rather than about a coin.
"""

from typing import Any

import pytest

from services import market_overview_service


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    """Answers the one GET `_fetch_global_market_data` makes."""

    def __init__(self, response: _Response | Exception) -> None:
        self._response = response

    async def get(self, _url: str, **_kwargs: Any) -> _Response:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


GLOBAL_PAYLOAD = {
    "data": {
        "total_market_cap": {"usd": 2.4e12},
        "market_cap_percentage": {"btc": 54.2, "eth": 12.8, "usdt": 4.6},
        "active_cryptocurrencies": 17_000,
    }
}


@pytest.mark.asyncio
async def test_global_block_carries_stablecoin_share():
    result = await market_overview_service._fetch_global_market_data(
        _Client(_Response(GLOBAL_PAYLOAD))
    )

    assert result["btc_dominance"] == pytest.approx(54.2)
    assert result["eth_dominance"] == pytest.approx(12.8)
    assert result["usdt_dominance"] == pytest.approx(4.6)


@pytest.mark.asyncio
async def test_missing_stablecoin_share_reads_as_zero_not_as_a_crash():
    """
    An older or partial `/global` response simply lacks the key. The ribbon
    treats an absent reading as "do not draw the bar", so a zero here is a gap
    rather than a claim — but it must not take the whole payload down with it.
    """
    payload = {"data": {**GLOBAL_PAYLOAD["data"], "market_cap_percentage": {"btc": 54.2}}}

    result = await market_overview_service._fetch_global_market_data(_Client(_Response(payload)))

    assert result["btc_dominance"] == pytest.approx(54.2)
    assert result["usdt_dominance"] == 0


@pytest.mark.asyncio
async def test_upstream_failure_yields_no_global_block_at_all():
    """
    Deliberately `{}` rather than a block of zeros: the caller fills the gap with
    its own defaults, and a fabricated 0% BTC dominance would render as a real
    reading on both surfaces that draw it.
    """
    assert (
        await market_overview_service._fetch_global_market_data(_Client(RuntimeError("no"))) == {}
    )
    assert (
        await market_overview_service._fetch_global_market_data(_Client(_Response({}, 503))) == {}
    )


def test_response_model_carries_stablecoin_share():
    """
    The route declares `response_model=MarketOverview`, and a response model
    *filters*: a field the service computes but the schema does not declare is
    dropped on the way out with no error anywhere. That is exactly how this
    reading went missing after it was added to the service — the payload was
    correct and the endpoint served it without the key.
    """
    from models.schemas import MarketOverview

    payload = MarketOverview(
        coins=[],
        total_volume_24h=1.0,
        total_market_cap=2.0,
        btc_dominance=54.2,
        eth_dominance=12.8,
        usdt_dominance=4.6,
        active_cryptocurrencies=17_000,
        timestamp="2026-08-27T00:00:00",
    ).model_dump()

    assert payload["usdt_dominance"] == pytest.approx(4.6)


def test_response_model_defaults_stablecoin_share_for_equities():
    """The same model answers `/api/nasdaq-overview`, which has no such reading."""
    from models.schemas import MarketOverview

    payload = MarketOverview(
        coins=[],
        total_volume_24h=1.0,
        total_market_cap=2.0,
        btc_dominance=0,
        active_cryptocurrencies=0,
        timestamp="2026-08-27T00:00:00",
    ).model_dump()

    assert payload["usdt_dominance"] == 0
