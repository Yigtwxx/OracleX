"""
How the KAP tape decides whether a reader waits.

The tape is a rolling buffer over a rate-limited source, so the interesting
question is not what it returns but *when it blocks*. Bringing the buffer up to
the head is a hundred-odd paced requests during a busy session; doing that
inside a reader's request is what made the KAP tab spin on every open that
followed two idle minutes. These tests pin the rule that replaced it: block only
when there is nothing at all to serve.
"""

import asyncio
import json
import time
from dataclasses import asdict

import pytest

from services.bist import kap_service as kap
from services.cache import bist_cache


def _disclosure(index: int) -> kap.Disclosure:
    return kap.Disclosure(
        index=index,
        title=f"Bildirim {index}",
        company="Test A.Ş.",
        ticker="TEST",
        category="ODA",
        category_label="Özel Durum Açıklaması",
        published_at="2026-08-31T10:00:00",
        summary=None,
        is_late=False,
        url=f"{kap.BASE}/{index}",
    )


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    # The tape file is real state on disk; point it at a scratch path so a test
    # never reads — or overwrites — the window the running terminal is using.
    monkeypatch.setattr(kap, "TAPE_FILE", str(tmp_path / "kap_tape.json"))
    monkeypatch.setattr(kap, "_disk_read", False)
    bist_cache.clear()
    kap._refresh_task = None
    yield
    bist_cache.clear()
    kap._refresh_task = None


class TestTapeBlocking:
    async def test_stale_buffer_is_served_without_waiting_for_the_walk(self, monkeypatch):
        """A stale tape answers from the buffer and catches up behind."""
        bist_cache.set(kap.BUFFER_KEY, [_disclosure(10), _disclosure(11)], kap.TTL_BUFFER)
        # `kap:fresh` is deliberately unset — the state two idle minutes leave.

        refreshes: list[str] = []

        async def _never_returns() -> list[kap.Disclosure]:
            refreshes.append("started")
            await asyncio.sleep(3600)
            return []

        monkeypatch.setattr(kap, "_refresh_buffer", _never_returns)

        rows = await asyncio.wait_for(kap.fetch_tape(limit=10), timeout=1.0)

        assert [d.index for d in rows] == [11, 10]
        # Let the scheduled task reach its first await before asserting on it.
        await asyncio.sleep(0)
        assert refreshes == ["started"]
        assert kap._refresh_task is not None
        kap._refresh_task.cancel()

    async def test_cold_buffer_still_waits(self, monkeypatch):
        """With nothing held there is nothing to serve, so the read blocks."""

        async def _fill() -> list[kap.Disclosure]:
            return [_disclosure(20)]

        monkeypatch.setattr(kap, "_refresh_buffer", _fill)

        rows = await kap.fetch_tape(limit=10)

        assert [d.index for d in rows] == [20]
        assert bist_cache.get("kap:fresh") is True

    async def test_fresh_tape_does_not_schedule_a_refresh(self, monkeypatch):
        """Inside the TTL the buffer is authoritative and nothing goes upstream."""
        bist_cache.set(kap.BUFFER_KEY, [_disclosure(30)], kap.TTL_BUFFER)
        bist_cache.set("kap:fresh", True, kap.TTL_TAPE)

        async def _explode() -> list[kap.Disclosure]:
            raise AssertionError("a fresh tape must not touch the network")

        monkeypatch.setattr(kap, "_refresh_buffer", _explode)

        assert [d.index for d in await kap.fetch_tape(limit=10)] == [30]
        assert kap._refresh_task is None


class TestScheduleRefresh:
    async def test_one_walk_at_a_time(self, monkeypatch):
        """Every reader in the stale window shares the one catch-up."""
        starts: list[int] = []

        async def _slow() -> list[kap.Disclosure]:
            starts.append(1)
            await asyncio.sleep(3600)
            return []

        monkeypatch.setattr(kap, "_refresh_buffer", _slow)

        kap._schedule_refresh()
        await asyncio.sleep(0)
        kap._schedule_refresh()
        kap._schedule_refresh()
        await asyncio.sleep(0)

        assert starts == [1]
        assert kap._refresh_task is not None
        kap._refresh_task.cancel()

    async def test_a_failed_walk_leaves_the_tape_stale_rather_than_marking_it_fresh(
        self, monkeypatch
    ):
        """
        Only a successful catch-up stamps `kap:fresh`.

        Otherwise one upstream blip would buy silence for the whole TTL, and the
        next reader would be served an unrefreshed buffer with nothing trying to
        fix it.
        """

        async def _fail() -> list[kap.Disclosure]:
            raise kap.KapUnavailable("upstream down")

        monkeypatch.setattr(kap, "_refresh_buffer", _fail)

        await kap._refresh_quietly()

        assert bist_cache.get("kap:fresh") is None


class TestTapePersistence:
    def test_a_written_window_is_read_back(self):
        """The point of the file: a restart is not a cold start."""
        kap._write_tape_file([_disclosure(40), _disclosure(41)])
        bist_cache.clear()
        kap._disk_read = False

        assert [d.index for d in kap._held_rows()] == [40, 41]
        # Known-good, so `find_head` walks forward instead of binary-searching.
        assert bist_cache.get("kap:head") == 41

    def test_a_window_older_than_the_stale_bound_is_ignored(self):
        """Week-old filings are real, but they are not "the tape"."""
        # Backdated in the file rather than by faking the clock: `kap.time` is
        # the stdlib module, so patching it also reaches `logging`.
        with open(kap.TAPE_FILE, "w") as handle:
            json.dump(
                {
                    "stored_at": time.time() - kap.MAX_STALE_TAPE - 1,
                    "rows": [asdict(_disclosure(50))],
                },
                handle,
            )

        assert kap._held_rows() == []

    def test_a_corrupt_file_is_not_a_failed_read(self):
        """A truncated write costs a cold start, not an outage."""
        with open(kap.TAPE_FILE, "w") as handle:
            handle.write('{"rows": [{"index": 1}')

        assert kap._held_rows() == []

    def test_a_missing_file_is_not_a_failed_read(self):
        assert kap._held_rows() == []

    async def test_a_refresh_writes_the_window_down(self, monkeypatch):
        monkeypatch.setattr(kap, "find_head", _head(60))
        monkeypatch.setattr(kap, "_gather", _gather_returning([_disclosure(60)]))

        await kap._refresh_buffer()

        assert [d.index for d in kap._read_tape_file()] == [60]


def _head(value: int):
    async def _find_head() -> int:
        return value

    return _find_head


def _gather_returning(rows: list[kap.Disclosure]):
    async def _gather(indices: list[int]) -> list[kap.Disclosure]:
        return rows

    return _gather


class TestRefreshWindow:
    """Which indices a catch-up actually asks for."""

    async def test_a_partial_window_backfills_below_its_own_top(self, monkeypatch):
        """
        A restored window that already reaches the head still fills itself out.

        Asking only for what is newer than the top would leave a nine-row tape
        nine rows forever, which is how a rate-limited restore used to strand
        the KAP board on a handful of filings.
        """
        held = [_disclosure(i) for i in (100, 99, 98)]
        bist_cache.set(kap.BUFFER_KEY, held, kap.TTL_BUFFER)
        monkeypatch.setattr(kap, "find_head", _head(100))
        monkeypatch.setattr(kap, "COLD_START_SPAN", 10)

        asked: list[int] = []
        monkeypatch.setattr(kap, "_gather", _recording_gather(asked))

        await kap._refresh_buffer()

        # Everything in the newest ten below the window, and nothing already held.
        assert asked == [97, 96, 95, 94, 93, 92, 91]

    async def test_gaps_inside_the_walked_span_are_not_asked_for_twice(self, monkeypatch):
        """
        A hole between two held indices is a withdrawn filing, not a miss.

        That span has already been walked, so re-asking spends a request against
        a host that rate-limits to be told the same thing.
        """
        held = [_disclosure(i) for i in (100, 98)]  # 99 was withdrawn.
        bist_cache.set(kap.BUFFER_KEY, held, kap.TTL_BUFFER)
        monkeypatch.setattr(kap, "find_head", _head(101))
        monkeypatch.setattr(kap, "COLD_START_SPAN", 3)

        asked: list[int] = []
        monkeypatch.setattr(kap, "_gather", _recording_gather(asked))

        await kap._refresh_buffer()

        assert asked == [101]

    async def test_the_steady_state_asks_only_for_what_is_new(self, monkeypatch):
        held = [_disclosure(i) for i in range(100, 90, -1)]
        bist_cache.set(kap.BUFFER_KEY, held, kap.TTL_BUFFER)
        monkeypatch.setattr(kap, "find_head", _head(102))
        monkeypatch.setattr(kap, "COLD_START_SPAN", 5)

        asked: list[int] = []
        monkeypatch.setattr(kap, "_gather", _recording_gather(asked))

        await kap._refresh_buffer()

        assert asked == [102, 101]


def _recording_gather(sink: list[int]):
    async def _gather(indices: list[int]) -> list[kap.Disclosure]:
        sink.extend(indices)
        return [_disclosure(i) for i in indices]

    return _gather


class TestRateLimitBackoff:
    """
    What the tape does when KAP says no.

    The flat two-minute pause this replaced is why the board sat at nine filings
    for an afternoon: the retry landed inside a block that outlasts it, took
    another 429, and armed the same two minutes again.
    """

    def test_each_consecutive_block_doubles_the_pause(self):
        kap._note_rate_limit()
        assert bist_cache.get(kap.BACKOFF_LEVEL_KEY) == 1

        kap._note_rate_limit()
        kap._note_rate_limit()

        assert bist_cache.get(kap.BACKOFF_LEVEL_KEY) == 3
        assert kap._rate_limited() is True

    def test_the_pause_is_capped(self, monkeypatch):
        """However long the block lasts, the tape keeps checking now and then."""
        pauses: list[int] = []
        real_set = bist_cache.set

        def _record(key, value, ttl):
            if key == "kap:backoff":
                pauses.append(ttl)
            real_set(key, value, ttl)

        monkeypatch.setattr(bist_cache, "set", _record)

        for _ in range(20):
            kap._note_rate_limit()

        assert max(pauses) == kap.RATE_LIMIT_BACKOFF_MAX_S

    def test_a_page_that_comes_back_resets_the_escalation(self):
        kap._note_rate_limit()
        kap._note_rate_limit()

        kap._note_rate_limit_cleared()

        assert bist_cache.get(kap.BACKOFF_LEVEL_KEY) is None
        # The next block starts counting from one again.
        kap._note_rate_limit()
        assert bist_cache.get(kap.BACKOFF_LEVEL_KEY) == 1
