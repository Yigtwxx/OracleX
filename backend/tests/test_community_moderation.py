"""
Tests for the moderator delete variants.

The owner path and the moderator path share a body and differ in exactly one
way: the moderator query carries no `user_id` filter. These tests assert that
difference directly, by recording the query that gets built, plus the existence
check the moderator path needs and the owner path gets for free.
"""

from types import SimpleNamespace

import pytest

from services.community import comments, posts
from services.community.errors import NotFound, NotOwner


class _Recorder:
    """
    A stand-in Supabase client that remembers the query chain built against it.

    Every builder method returns `self` and appends `(name, args)`, so a test can
    assert on the filters a query carried without a database.
    """

    def __init__(self):
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return self

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args))
            return self

        return _record

    def execute(self):
        self.calls.append(("execute", ()))
        return SimpleNamespace(data=[])

    def filters(self, name):
        return [args for call, args in self.calls if call == name]


@pytest.fixture
def db(monkeypatch):
    """
    Stub `table_op` for both community modules.

    `what` is how the stub tells the existence lookup from the write — it is the
    same string the production code passes for the log line.
    """
    recorder = _Recorder()
    state = {"owner": "author-1", "exists": True}

    async def _table_op(operation, *, what):
        if what in ("load post owner", "load comment owner"):
            return [{"user_id": state["owner"]}] if state["exists"] else []
        operation(recorder)
        return None

    monkeypatch.setattr(posts._db, "table_op", _table_op)
    return SimpleNamespace(recorder=recorder, state=state)


# ── posts ────────────────────────────────────────────────────────────────────


async def test_a_moderator_delete_carries_no_owner_filter(db):
    await posts.delete_post_as_moderator(post_id="post-1")

    assert ("delete", ()) in db.recorder.calls
    assert db.recorder.filters("eq") == [("id", "post-1")]


async def test_an_owner_delete_still_filters_on_the_owner(db):
    """Belt and braces after `_assert_owner`, and worth keeping."""
    await posts.delete_post(post_id="post-1", user_id="author-1")

    assert db.recorder.filters("eq") == [("id", "post-1"), ("user_id", "author-1")]


async def test_a_moderator_delete_of_a_missing_post_raises_not_found(db):
    """
    Without the existence check this would be a silent 204: a delete matching
    zero rows is not an error in PostgREST.
    """
    db.state["exists"] = False

    with pytest.raises(NotFound):
        await posts.delete_post_as_moderator(post_id="ghost")

    assert db.recorder.calls == [], "nothing should have been written"


async def test_a_non_owner_delete_is_still_refused(db):
    with pytest.raises(NotOwner):
        await posts.delete_post(post_id="post-1", user_id="somebody-else")


# ── comments ─────────────────────────────────────────────────────────────────


async def test_a_moderator_comment_delete_tombstones_without_an_owner_filter(db):
    await comments.delete_comment_as_moderator(comment_id="c-1")

    assert db.recorder.filters("eq") == [("id", "c-1")]
    # The tombstone, not a row delete: replies have to stay readable.
    assert ("delete", ()) not in db.recorder.calls
    patch = db.recorder.filters("update")[0][0]
    assert patch["content"] == ""
    assert patch["deleted_at"]


async def test_a_moderator_comment_delete_stays_idempotent(db):
    """
    `.is_("deleted_at", "null")` is what stops a second delete from re-stamping
    the row — which matters because the comments_count trigger fires on the
    transition.
    """
    await comments.delete_comment_as_moderator(comment_id="c-1")

    assert ("is_", ("deleted_at", "null")) in db.recorder.calls


async def test_an_owner_comment_delete_still_filters_on_the_owner(db):
    await comments.delete_comment(comment_id="c-1", user_id="author-1")

    assert db.recorder.filters("eq") == [("id", "c-1"), ("user_id", "author-1")]


async def test_a_moderator_delete_of_a_missing_comment_raises_not_found(db):
    db.state["exists"] = False

    with pytest.raises(NotFound):
        await comments.delete_comment_as_moderator(comment_id="ghost")

    assert db.recorder.calls == []
