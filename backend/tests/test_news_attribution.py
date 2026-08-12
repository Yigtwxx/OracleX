"""
Attribution is worked out once per headline and remembered.

The feeds are re-read every couple of minutes and return largely the same
items, so without a memory every refresh sent the whole batch back through the
LLM. That was slow enough that calls timed out, and a timeout downgrades
detection to the heuristic path — which is how one story could be filed under
one asset at 10:00 and a different one at 10:02.
"""

import asyncio

import pytest

from services import news_attribution as na
from services.symbol_detection_service import Attribution


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """A fresh, throwaway store per test — no disk state carried between them."""
    monkeypatch.setattr(na, "ATTRIBUTION_FILE", str(tmp_path / "attribution.json"))
    monkeypatch.setattr(na, "_entries", None)
    monkeypatch.setattr(na, "_unsaved", 0)
    yield


def fake_detector(monkeypatch, *results):
    """Queue up detector results and record how often it was called."""
    calls = []
    queue = list(results)

    async def detect(text, title, hint):
        calls.append(title)
        return queue.pop(0) if queue else Attribution(None, hint)

    monkeypatch.setattr(na, "detect_symbol_smart", detect)
    return calls


def get(news_id, title, summary="", hint="crypto"):
    return asyncio.run(na.get_or_detect(news_id, title, summary, hint))


class TestDetectionHappensOnce:
    def test_second_lookup_does_not_call_the_detector(self, monkeypatch):
        calls = fake_detector(monkeypatch, Attribution("BINANCE:BTCUSDT", "crypto"))

        first = get("id-1", "Bitcoin rallies")
        second = get("id-1", "Bitcoin rallies")

        assert first == second
        assert len(calls) == 1

    def test_unattributed_results_are_cached_too(self, monkeypatch):
        """
        "This is about no tradeable asset" costs exactly as much to work out as
        any other answer, so it is not recomputed either.
        """
        calls = fake_detector(monkeypatch, Attribution(None, "crypto"))

        assert get("id-2", "Fed holds rates").symbol is None
        assert get("id-2", "Fed holds rates").symbol is None
        assert len(calls) == 1

    def test_the_symbol_does_not_change_between_refreshes(self, monkeypatch):
        """A second, different detector answer must not reach a cached item."""
        fake_detector(
            monkeypatch,
            Attribution("BINANCE:BTCUSDT", "crypto"),
            Attribution("BINANCE:ETHUSDT", "crypto"),
        )

        assert get("id-3", "Bitcoin rallies").symbol == "BINANCE:BTCUSDT"
        assert get("id-3", "Bitcoin rallies").symbol == "BINANCE:BTCUSDT"


class TestDegradedResultsAreRevisited:
    def test_unconfident_result_is_detected_again(self, monkeypatch):
        """
        A name match made while no model was reachable is the best guess
        available, but it is not settled — the next pass gets to improve it.
        """
        calls = fake_detector(
            monkeypatch,
            Attribution("BINANCE:BTCUSDT", "crypto", confident=False),
            Attribution("NASDAQ:COIN", "stock", confident=True),
        )

        assert get("id-4", "Coinbase and bitcoin").symbol == "BINANCE:BTCUSDT"
        second = get("id-4", "Coinbase and bitcoin")

        assert second.symbol == "NASDAQ:COIN"
        assert second.asset_type == "stock"
        assert len(calls) == 2

    def test_a_failed_retry_keeps_the_previous_answer(self, monkeypatch):
        """Re-detection that finds nothing must not erase a plausible symbol."""
        fake_detector(
            monkeypatch,
            Attribution("BINANCE:BTCUSDT", "crypto", confident=False),
            Attribution(None, "crypto", confident=False),
        )

        assert get("id-5", "Bitcoin rallies").symbol == "BINANCE:BTCUSDT"
        assert get("id-5", "Bitcoin rallies").symbol == "BINANCE:BTCUSDT"


class TestPersistence:
    def test_a_restart_does_not_repeat_the_batch(self, monkeypatch):
        calls = fake_detector(monkeypatch, Attribution("NASDAQ:AAPL", "stock"))

        get("id-6", "Apple ships a thing", hint="stock")
        asyncio.run(na.flush())

        # Simulate a fresh process: in-memory state cleared, file left in place.
        monkeypatch.setattr(na, "_entries", None)
        monkeypatch.setattr(na, "_unsaved", 0)

        restored = get("id-6", "Apple ships a thing", hint="stock")

        assert restored.symbol == "NASDAQ:AAPL"
        assert restored.asset_type == "stock"
        assert len(calls) == 1

    def test_a_logic_change_discards_the_store(self, monkeypatch):
        """
        Cached answers must not outlive the rules that produced them, or a fix
        never reaches the items that needed it.
        """
        calls = fake_detector(
            monkeypatch,
            Attribution("BINANCE:AIUSDT", "crypto"),
            Attribution(None, "crypto"),
        )

        get("id-7", "AI infrastructure spending accelerates")
        asyncio.run(na.flush())

        monkeypatch.setattr(na, "_entries", None)
        monkeypatch.setattr(na, "_unsaved", 0)
        monkeypatch.setattr(na, "ATTRIBUTION_LOGIC_VERSION", na.ATTRIBUTION_LOGIC_VERSION + 1)

        assert get("id-7", "AI infrastructure spending accelerates").symbol is None
        assert len(calls) == 2

    def test_the_store_is_pruned_to_its_cap(self, monkeypatch):
        monkeypatch.setattr(na, "MAX_ATTRIBUTION_ENTRIES", 10)
        fake_detector(monkeypatch, *[Attribution(None, "crypto") for _ in range(40)])

        for i in range(40):
            get(f"id-{i}", f"Headline {i}")
        asyncio.run(na.flush())

        assert len(na._load()) <= 10
