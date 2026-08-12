"""
Tests for the suspension lookup.

Service level, no HTTP. The policy decisions worth pinning here are the ones a
reader would otherwise have to infer: a suspension that lifts itself, a cache
that cannot outlive the suspension it holds, and a lookup failure that lets the
caller through rather than locking the site.
"""

from datetime import datetime, timedelta, UTC

import pytest

from services.admin import bans


@pytest.fixture(autouse=True)
def clean_cache():
    bans.clear_cache()
    yield
    bans.clear_cache()


@pytest.fixture
def rows(monkeypatch):
    """Stub the database with a fixed row, counting how often it is asked."""
    calls = {"n": 0}

    def _serve(row):
        async def _table_op(operation, *, what):
            calls["n"] += 1
            return [row] if row is not None else []

        monkeypatch.setattr(bans._db, "table_op", _table_op)
        return calls

    return _serve


async def test_a_null_banned_until_is_not_a_suspension(rows):
    rows({"banned_until": None, "ban_reason": None})
    assert await bans.check("user-1") is None


async def test_a_missing_profile_is_not_a_suspension(rows):
    rows(None)
    assert await bans.check("user-1") is None


async def test_a_past_banned_until_has_already_lifted(rows):
    """No cron job clears these — the comparison does."""
    past = datetime.now(UTC) - timedelta(hours=1)
    rows({"banned_until": past.isoformat(), "ban_reason": "spam"})
    assert await bans.check("user-1") is None


async def test_a_future_banned_until_is_a_suspension(rows):
    until = datetime.now(UTC) + timedelta(days=2)
    rows({"banned_until": until.isoformat(), "ban_reason": "spam"})

    state = await bans.check("user-1")

    assert state is not None
    assert state.reason == "spam"
    assert not state.is_permanent


async def test_the_far_future_sentinel_reads_as_permanent(rows):
    rows({"banned_until": bans.PERMANENT_UNTIL.isoformat(), "ban_reason": None})
    state = await bans.check("user-1")
    assert state is not None and state.is_permanent


async def test_an_unparseable_timestamp_is_treated_as_no_suspension(rows):
    """Never lock somebody out over a value we failed to read."""
    rows({"banned_until": "not-a-date", "ban_reason": None})
    assert await bans.check("user-1") is None


async def test_the_answer_is_cached_within_the_ttl(rows):
    calls = rows({"banned_until": None, "ban_reason": None})

    await bans.check("user-1")
    await bans.check("user-1")
    await bans.check("user-1")

    assert calls["n"] == 1, f"expected one query, made {calls['n']}"


async def test_a_different_user_is_a_different_cache_entry(rows):
    calls = rows({"banned_until": None, "ban_reason": None})

    await bans.check("user-1")
    await bans.check("user-2")

    assert calls["n"] == 2


async def test_invalidate_forces_a_refetch(rows):
    calls = rows({"banned_until": None, "ban_reason": None})

    await bans.check("user-1")
    await bans.invalidate("user-1")
    await bans.check("user-1")

    assert calls["n"] == 2


async def test_a_cached_suspension_stops_applying_once_it_expires(rows, monkeypatch):
    """
    The cached value can outlive the suspension it describes. A lifted ban that
    keeps blocking for another minute is worse than re-checking the clock.
    """
    until = datetime.now(UTC) + timedelta(seconds=1)
    rows({"banned_until": until.isoformat(), "ban_reason": None})

    assert await bans.check("user-1") is not None

    real_now = datetime.now

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now(tz) + timedelta(minutes=5)

    monkeypatch.setattr(bans, "datetime", _Later)
    assert await bans.check("user-1") is None


async def test_a_failed_lookup_fails_open(monkeypatch):
    """
    A Postgres blip must not 403 every signed-in user on the site. The worst
    case here is a suspended account posting during an outage; the worst case of
    failing closed is a self-inflicted site-wide outage.
    """

    async def _boom(operation, *, what):
        raise RuntimeError("supabase is down")

    monkeypatch.setattr(bans._db, "table_op", _boom)
    assert await bans.check("user-1") is None


async def test_a_failed_lookup_is_not_cached(monkeypatch):
    """Recovery has to be immediate, not TTL-delayed."""
    calls = {"n": 0}

    async def _boom(operation, *, what):
        calls["n"] += 1
        raise RuntimeError("supabase is down")

    monkeypatch.setattr(bans._db, "table_op", _boom)
    await bans.check("user-1")
    await bans.check("user-1")

    assert calls["n"] == 2
