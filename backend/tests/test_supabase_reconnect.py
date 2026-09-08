"""
Tests for surviving a dropped Supabase connection.

The failure being reproduced here: `supabase-py` holds one httpx client, and
httpx speaks HTTP/2 to Supabase, so *every* query this process makes is
multiplexed over a single TCP connection. When the edge closes that connection,
`httpcore` raises `RemoteProtocolError("Server disconnected")` — and its own
comment at the raise site says the exception is then replayed on every pending
read, so one close fails every request in flight at once.

Observed as two services failing in the same second, one of them turning it into
a 503 on `/api/profile` for a signed-in reader whose profile was fine.
"""

import pytest
from httpcore import RemoteProtocolError

from services import supabase_service as svc


class _Boom:
    """Fails the first `times` calls the way a dropped connection does."""

    def __init__(self, times: int, error: BaseException | None = None):
        self.calls = 0
        self._times = times
        self._error = error or RemoteProtocolError("Server disconnected")

    def __call__(self):
        self.calls += 1
        if self.calls <= self._times:
            raise self._error
        return "ok"


def test_retries_once_after_a_dropped_connection():
    op = _Boom(times=1)
    assert svc.run_with_reconnect(op) == "ok"
    assert op.calls == 2


def test_returns_immediately_when_nothing_is_wrong():
    op = _Boom(times=0)
    assert svc.run_with_reconnect(op) == "ok"
    assert op.calls == 1


def test_gives_up_rather_than_retrying_forever():
    """A genuinely unreachable database must surface, not spin."""
    op = _Boom(times=99)
    with pytest.raises(RemoteProtocolError):
        svc.run_with_reconnect(op)
    assert op.calls == 2


def test_does_not_retry_an_error_that_is_not_a_disconnect():
    """
    A retry only helps when the server never answered. A real error — a
    constraint violation, a bad filter — would just be repeated, and for a write
    that is how one click becomes two rows.
    """
    op = _Boom(times=1, error=ValueError("duplicate key value violates unique constraint"))
    with pytest.raises(ValueError):
        svc.run_with_reconnect(op)
    assert op.calls == 1


@pytest.mark.parametrize(
    "message",
    [
        "Server disconnected",  # httpcore's HTTP/2 wording
        "Server disconnected without sending a response.",  # its HTTP/1.1 wording
    ],
)
def test_recognises_both_httpcore_wordings(message):
    op = _Boom(times=1, error=RemoteProtocolError(message))
    assert svc.run_with_reconnect(op) == "ok"
    assert op.calls == 2


def test_a_disconnect_shaped_message_on_another_type_is_not_retried():
    """
    supabase-py wraps some failures, so the type alone is not the signal — but a
    library that merely *mentions* a disconnect in a message it raised itself is
    not the same event, and guessing would retry real errors.
    """
    op = _Boom(times=1, error=ValueError("Server disconnected"))
    with pytest.raises(ValueError):
        svc.run_with_reconnect(op)
    assert op.calls == 1


@pytest.mark.asyncio
async def test_supabase_ops_survives_one_disconnect(monkeypatch):
    """The central async wrapper, which is how most domains reach the database."""
    from services.db import SupabaseOps

    class Failure(Exception):
        pass

    ops = SupabaseOps(domain="test", wrap=Failure)
    op = _Boom(times=1)

    assert await ops.run(op, what="select something") == "ok"
    assert op.calls == 2


@pytest.mark.asyncio
async def test_supabase_ops_still_wraps_a_real_failure():
    from services.db import SupabaseOps

    class Failure(Exception):
        pass

    ops = SupabaseOps(domain="test", wrap=Failure)

    def broken():
        raise ValueError("no such column")

    with pytest.raises(Failure):
        await ops.run(broken, what="select something")


@pytest.mark.asyncio
async def test_get_user_profile_survives_one_disconnect(monkeypatch):
    """
    The exact 503 this was opened for: a signed-in reader whose profile row was
    fine, told "Your profile is unavailable right now" because the shared
    connection happened to close mid-request.
    """
    from services import profile_service

    calls = {"n": 0}

    class FakeQuery:
        def table(self, _name):
            return self

        def select(self, *_a, **_kw):
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RemoteProtocolError("Server disconnected")
            return type("R", (), {"data": [{"id": "u1", "subscription_tier": "free"}]})()

    monkeypatch.setattr(profile_service, "get_supabase", FakeQuery)

    profile = await profile_service.get_user_profile("u1")

    assert calls["n"] == 2
    assert profile["id"] == "u1"


@pytest.mark.asyncio
async def test_get_user_profile_still_raises_when_the_database_is_really_down(monkeypatch):
    """
    The behaviour the 503 exists for must survive the retry being added.

    It was introduced because swallowing the error and returning a fabricated
    free-plan profile told a paying subscriber they were on Free every time
    Supabase hiccuped; one retry must not quietly restore that.
    """
    from services import profile_service

    calls = {"n": 0}

    class AlwaysDown:
        def table(self, _name):
            return self

        def select(self, *_a, **_kw):
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            calls["n"] += 1
            raise RemoteProtocolError("Server disconnected")

    monkeypatch.setattr(profile_service, "get_supabase", AlwaysDown)

    with pytest.raises(profile_service.ProfileError):
        await profile_service.get_user_profile("u1")

    assert calls["n"] == 2, "retried once, then surfaced"
