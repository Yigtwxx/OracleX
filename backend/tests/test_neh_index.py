"""
Tests for the Nothing Ever Happens Index.

Scored against hand-built baskets rather than a saved capture: the properties
that matter — that the maximum wins and not the mean, that a malformed price is
dropped instead of clamped, that band boundaries land on the source's own edges —
are exactly the cases a real basket happens not to contain on any given day.
"""

import pytest

from services import neh_index_service as neh
from services.neh_index_service import (
    NehSourceUnavailable,
    fetch_neh_index,
    score,
)


def _market(slug: str, price, *, region: str = "global") -> dict:
    return {"slug": slug, "label": slug.replace("-", " "), "region": region, "price": price}


def test_index_is_the_highest_probability_not_the_mean():
    payload = score([_market("a", 0.05), _market("b", 0.28), _market("c", 0.02)])

    assert payload["index"] == 28
    assert payload["top"]["slug"] == "b"
    assert payload["markets_tracked"] == 3


@pytest.mark.parametrize(
    ("price", "status", "label"),
    [
        (0.00, "calm", "Nothing Ever Happens"),
        (0.29, "calm", "Nothing Ever Happens"),
        (0.30, "watch", "Something Might Happen"),
        (0.64, "watch", "Something Might Happen"),
        (0.65, "happening", "Something Is Happening"),
        (0.98, "happening", "Something Is Happening"),
        (0.99, "happened", "It Happened"),
        (1.00, "happened", "It Happened"),
    ],
)
def test_band_edges_match_the_source(price, status, label):
    payload = score([_market("only", price)])

    assert payload["status"] == status
    assert payload["label"] == label


def test_unusable_prices_are_dropped_rather_than_clamped():
    payload = score([_market("bad", 1.4), _market("worse", "0.9"), _market("good", 0.11)])

    assert payload["index"] == 11
    assert payload["markets_tracked"] == 1


def test_a_basket_with_nothing_usable_is_an_outage_not_a_calm_world():
    with pytest.raises(NehSourceUnavailable):
        score([_market("bad", None), _market("worse", -1)])


@pytest.mark.asyncio
async def test_fetch_replays_the_last_reading_when_the_source_fails(monkeypatch):
    calls = {"n": 0}

    async def fake_get_json(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"markets": [_market("a", 0.42)], "lowVolume": [], "timestamp": "now"}
        raise RuntimeError("upstream down")

    monkeypatch.setattr(neh, "get_json", fake_get_json)
    neh.home_cache.clear()

    first = await fetch_neh_index()
    assert first["index"] == 42
    assert first["stale"] is False

    # Expire the live entry while leaving the fallback behind, which is the
    # state a real second call after the TTL lapses would find.
    neh.home_cache.invalidate(neh.CACHE_KEY)

    replayed = await fetch_neh_index()
    assert replayed["index"] == 42
    assert replayed["stale"] is True


@pytest.mark.asyncio
async def test_fetch_reports_unavailable_when_there_is_nothing_to_replay(monkeypatch):
    async def fake_get_json(url, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(neh, "get_json", fake_get_json)
    neh.home_cache.clear()

    payload = await fetch_neh_index()

    assert payload["index"] is None
    assert payload["status"] == "unavailable"
    assert payload["top"] is None


@pytest.mark.asyncio
async def test_low_volume_markets_never_reach_the_index(monkeypatch):
    async def fake_get_json(url, **kwargs):
        return {
            "markets": [_market("traded", 0.12)],
            "lowVolume": [_market("thin", 0.95)],
            "timestamp": "now",
        }

    monkeypatch.setattr(neh, "get_json", fake_get_json)
    neh.home_cache.clear()

    payload = await fetch_neh_index()

    assert payload["index"] == 12
