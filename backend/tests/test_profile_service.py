"""
Regression tests for four bugs in the profile service.

Each one was silent — the code reported success, or invented an answer, and
nothing downstream could tell. They are pinned here because all four are the
kind that come back the moment somebody "simplifies" the surrounding function.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from services import profile_service


class FakeQuery:
    """
    A chainable PostgREST double.

    Every builder method returns self and records the call; `execute` hands back
    whatever the test queued. Enough to drive this service, which only ever uses
    select/eq/limit/update/upsert/insert.
    """

    def __init__(self, result, recorder: list):
        self._result = result
        self._recorder = recorder

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            self._recorder.append((name, args))
            return self

        return _call

    def execute(self):
        self._recorder.append(("execute", ()))
        if isinstance(self._result, Exception):
            raise self._result
        return SimpleNamespace(data=self._result)


class FakeClient:
    """Serves one queued result per table, in order."""

    def __init__(self, results: dict):
        self._results = {table: list(values) for table, values in results.items()}
        self.calls: list = []

    def table(self, name: str):
        queue = self._results.get(name, [])
        result = queue.pop(0) if queue else []
        self.calls.append(("table", (name,)))
        return FakeQuery(result, self.calls)


@pytest.fixture
def fake_db(monkeypatch):
    def _install(results: dict) -> FakeClient:
        client = FakeClient(results)
        monkeypatch.setattr(profile_service, "get_supabase", lambda: client)
        return client

    return _install


# ── update_user_profile: an update that matched nothing is not a success ────


@pytest.mark.asyncio
async def test_update_user_profile_returns_false_when_no_row_matched(fake_db):
    """
    PostgREST answers an update that matched nothing with `[]`.

    The old test was `response.data is not None`, and `[] is not None` is True —
    so every write to a profile that did not exist reported success and the
    router returned 200.
    """
    fake_db({"profiles": [[]]})

    result = await profile_service.update_user_profile("ghost", {"full_name": "Nobody"})

    assert result is False, "An update matching zero rows must not report success"


@pytest.mark.asyncio
async def test_update_user_profile_returns_true_when_a_row_was_written(fake_db):
    fake_db({"profiles": [[{"id": "user-abc", "full_name": "Ada"}]]})

    result = await profile_service.update_user_profile("user-abc", {"full_name": "Ada"})

    assert result is True


@pytest.mark.asyncio
async def test_a_failed_write_is_not_reported_as_a_missing_profile(fake_db):
    """
    Regression. The write failing and no row matching used to be the same
    `False`, and the router turns `False` into 404 "Profile not found".

    That is the wrong thing to say and it costs real debugging time: saving a
    bio while `profiles.bio` did not exist answered "Profile not found" when the
    profile was right there and the *column* was missing. A caller cannot tell a
    404 that means "you do not exist" from one that means "the database refused
    us", so the two have to be different outcomes here.
    """
    fake_db({"profiles": [RuntimeError("Could not find the 'bio' column")]})

    with pytest.raises(profile_service.ProfileStoreError):
        await profile_service.update_user_profile("user-abc", {"bio": "Hello"})


@pytest.mark.asyncio
async def test_a_write_that_matched_nothing_still_returns_false(fake_db):
    """The other half: a genuinely missing profile stays a plain False, not a raise."""
    fake_db({"profiles": [[]]})

    assert await profile_service.update_user_profile("ghost", {"full_name": "Nobody"}) is False


@pytest.mark.asyncio
async def test_a_broken_write_does_not_break_reading_the_profile(fake_db):
    """
    The counter reset inside `get_user_profile` is a side effect, not the point
    of the call. It must not turn a readable profile into an error.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    fake_db(
        {
            "profiles": [
                [{"id": "user-abc", "ai_queries_today": 3, "ai_queries_reset_at": yesterday}],
                RuntimeError("write refused"),
            ]
        }
    )

    profile = await profile_service.get_user_profile("user-abc")

    assert profile is not None
    assert profile["id"] == "user-abc"


@pytest.mark.asyncio
async def test_update_user_profile_drops_fields_outside_the_allowlist(fake_db):
    client = fake_db({"profiles": [[{"id": "user-abc"}]]})

    await profile_service.update_user_profile(
        "user-abc", {"full_name": "Ada", "banned_until": "9999-01-01", "id": "someone-else"}
    )

    written = next(args[0] for name, args in client.calls if name == "update")
    assert set(written) == {"full_name", "updated_at"}, f"Unexpected columns written: {written}"


# ── get_user_profile: no fabricated profile, and the email gets written ────


@pytest.mark.asyncio
async def test_get_user_profile_raises_instead_of_inventing_a_free_plan(fake_db):
    """
    It used to swallow the exception and return a hardcoded free-plan profile,
    so a Whale subscriber was shown "Free, 5 queries" whenever Supabase blipped.
    """
    fake_db({"profiles": [RuntimeError("connection refused")]})

    with pytest.raises(profile_service.ProfileError):
        await profile_service.get_user_profile("user-abc")


@pytest.mark.asyncio
async def test_get_user_profile_writes_the_email_on_a_profile_it_creates(fake_db):
    """
    `profiles.email` is what the admin list and the sign-up duplicate check read.
    The auto-create path never wrote it, leaving those rows invisible to both.
    """
    client = fake_db({"profiles": [[], []]})

    profile = await profile_service.get_user_profile("user-abc", email="abc@example.com")

    upserted = next(args[0] for name, args in client.calls if name == "upsert")
    assert upserted["email"] == "abc@example.com"
    assert profile["email"] == "abc@example.com"


@pytest.mark.asyncio
async def test_get_user_profile_computes_the_query_allowance_from_the_plan(fake_db):
    fake_db({"profiles": [[{"id": "user-abc", "subscription_plan": "pro", "ai_queries_today": 3}]]})

    profile = await profile_service.get_user_profile("user-abc")

    assert profile["ai_query_limit"] == 999999
    assert profile["ai_queries_remaining"] == 999996


# ── get_user_settings: the default-insert branch has to be reachable ───────


@pytest.mark.asyncio
async def test_get_user_settings_inserts_defaults_when_no_row_exists(fake_db):
    """
    The query used `.single()`, which raises on zero rows — so control jumped
    straight to the exception handler and the insert below it never ran. Every
    new user got an in-memory default that was never stored.
    """
    client = fake_db({"user_settings": [[], []]})

    settings = await profile_service.get_user_settings("user-abc")

    inserted = [args[0] for name, args in client.calls if name == "insert"]
    assert inserted, "Defaults must actually be written, not just returned"
    assert inserted[0]["user_id"] == "user-abc"
    assert settings["default_market"] == "crypto"


@pytest.mark.asyncio
async def test_get_user_settings_returns_the_stored_row_when_one_exists(fake_db):
    client = fake_db({"user_settings": [[{"user_id": "user-abc", "default_market": "nasdaq"}]]})

    settings = await profile_service.get_user_settings("user-abc")

    assert settings["default_market"] == "nasdaq"
    assert not [name for name, _ in client.calls if name == "insert"]


# ── delete_account: storage first, best-effort, then the auth row ──────────


@pytest.mark.asyncio
async def test_delete_account_clears_storage_then_deletes_the_auth_user(monkeypatch):
    order: list = []

    async def _list(*, bucket, user_id):
        order.append(f"list:{bucket}")
        return [f"{user_id}/a.png"]

    async def _remove(*, bucket, paths):
        order.append(f"remove:{bucket}")

    monkeypatch.setattr(profile_service.storage, "list_user_objects", _list)
    monkeypatch.setattr(profile_service.storage, "remove_objects", _remove)

    deleted: list = []
    admin = SimpleNamespace(delete_user=lambda uid: deleted.append(uid) or order.append("auth"))
    monkeypatch.setattr(
        profile_service,
        "get_supabase",
        lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)),
    )

    await profile_service.delete_account("user-abc")

    assert deleted == ["user-abc"]
    assert order.index("auth") == len(order) - 1, (
        "The auth row must go last — storage is unreachable once the user is gone"
    )
    assert "remove:profile-avatars" in order
    assert "remove:community-media" in order


@pytest.mark.asyncio
async def test_delete_account_proceeds_when_storage_cleanup_fails(monkeypatch):
    """Orphaned bytes in a bucket beat an account that is half deleted."""

    async def _boom(**kwargs):
        raise RuntimeError("bucket is down")

    monkeypatch.setattr(profile_service.storage, "list_user_objects", _boom)
    monkeypatch.setattr(profile_service.storage, "remove_objects", _boom)

    deleted: list = []
    admin = SimpleNamespace(delete_user=deleted.append)
    monkeypatch.setattr(
        profile_service,
        "get_supabase",
        lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)),
    )

    await profile_service.delete_account("user-abc")

    assert deleted == ["user-abc"]


@pytest.mark.asyncio
async def test_delete_account_raises_when_the_auth_row_cannot_be_removed(monkeypatch):
    async def _noop(**kwargs):
        return []

    monkeypatch.setattr(profile_service.storage, "list_user_objects", _noop)
    monkeypatch.setattr(profile_service.storage, "remove_objects", _noop)

    def _fail(_uid):
        raise RuntimeError("gotrue is down")

    monkeypatch.setattr(
        profile_service,
        "get_supabase",
        lambda: SimpleNamespace(auth=SimpleNamespace(admin=SimpleNamespace(delete_user=_fail))),
    )

    with pytest.raises(profile_service.ProfileError):
        await profile_service.delete_account("user-abc")
