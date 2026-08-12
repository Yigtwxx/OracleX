"""
Service-level tests for the admin actions themselves.

The two refusals in `ban_user` get the most attention here, and deserve it: a
suspension is enforced inside `get_current_user`, so suspending an admin account
would lock away every authenticated route including the one that undoes it. Only
a manual SQL edit would recover from that.
"""

from datetime import datetime, timedelta, UTC

import pytest

from services.admin import audit, bans, moderation, users
from services.admin.audit import AuditActor
from services.admin.errors import InvalidRequest, NotFound, ProtectedTarget

ACTOR = AuditActor(id="user-admin", email="admin@example.com")


@pytest.fixture
def rows(monkeypatch):
    """Stub the `get_admin_users` RPC with one row, and record every write."""
    written: list = []
    row = {
        "id": "user-1",
        "email": "someone@example.com",
        "full_name": "Someone",
        "subscription_plan": "free",
        "created_at": datetime.now(UTC).isoformat(),
        "banned_until": None,
        "ban_reason": None,
        "posts_count": 2,
        "comments_count": 5,
        "total_count": 1,
    }

    async def _rpc(name, params):
        if name == "get_admin_users":
            return [row] if params.get("p_user_id") in (None, row["id"]) else []
        return []

    async def _table_op(operation, *, what):
        written.append(what)
        return None

    monkeypatch.setattr(users._db, "rpc", _rpc)
    monkeypatch.setattr(users._db, "table_op", _table_op)
    return {"row": row, "written": written}


@pytest.fixture(autouse=True)
def silence_audit(monkeypatch):
    """Record audit entries instead of writing them."""
    entries: list = []

    async def _record(**kwargs):
        entries.append(kwargs)

    monkeypatch.setattr(audit, "record", _record)
    return entries


# ── the guards ───────────────────────────────────────────────────────────────


async def test_suspending_yourself_is_refused(rows):
    rows["row"]["id"] = ACTOR.id

    with pytest.raises(ProtectedTarget):
        await users.ban_user(user_id=ACTOR.id, actor=ACTOR)

    assert rows["written"] == [], "nothing should have been written"


async def test_suspending_an_admin_account_is_refused(rows, admin_emails):
    rows["row"]["email"] = admin_emails

    with pytest.raises(ProtectedTarget):
        await users.ban_user(user_id="user-1", actor=ACTOR)

    assert rows["written"] == []


async def test_suspending_an_ordinary_account_is_allowed(rows, admin_emails):
    await users.ban_user(user_id="user-1", days=7, reason="spam", actor=ACTOR)

    assert "ban user" in rows["written"]


async def test_suspending_a_missing_user_is_not_found(rows):
    with pytest.raises(NotFound):
        await users.ban_user(user_id="ghost", actor=ACTOR)


# ── suspension shape ─────────────────────────────────────────────────────────


async def test_a_suspension_without_days_is_permanent(rows, monkeypatch, silence_audit):
    captured = {}

    async def _table_op(operation, *, what):
        captured["what"] = what
        return None

    monkeypatch.setattr(users._db, "table_op", _table_op)

    await users.ban_user(user_id="user-1", actor=ACTOR)

    entry = silence_audit[-1]
    assert entry["metadata"]["until"] == bans.PERMANENT_UNTIL.isoformat()


async def test_a_suspension_invalidates_the_cached_decision(rows, monkeypatch):
    """Otherwise the ban would not bite for up to the cache TTL."""
    invalidated: list = []

    async def _invalidate(user_id):
        invalidated.append(user_id)

    monkeypatch.setattr(bans, "invalidate", _invalidate)

    await users.ban_user(user_id="user-1", days=1, actor=ACTOR)
    assert invalidated == ["user-1"]


async def test_lifting_a_suspension_invalidates_it_too(rows, monkeypatch):
    invalidated: list = []

    async def _invalidate(user_id):
        invalidated.append(user_id)

    monkeypatch.setattr(bans, "invalidate", _invalidate)

    await users.unban_user(user_id="user-1", actor=ACTOR)
    assert invalidated == ["user-1"]


# ── plans ────────────────────────────────────────────────────────────────────


async def test_an_unknown_plan_is_refused(rows):
    with pytest.raises(InvalidRequest):
        await users.set_plan(user_id="user-1", plan="platinum", actor=ACTOR)

    assert rows["written"] == []


async def test_a_plan_without_a_duration_does_not_expire(rows, silence_audit):
    """
    `get_subscription` downgrades an expired plan to free, so an admin grant
    with no duration has to mean no expiry or it quietly undoes itself.
    """
    await users.set_plan(user_id="user-1", plan="whale", actor=ACTOR)

    assert silence_audit[-1]["metadata"]["duration_days"] is None


async def test_a_plan_change_is_audited_with_both_ends(rows, silence_audit):
    await users.set_plan(user_id="user-1", plan="pro", duration_days=30, actor=ACTOR)

    metadata = silence_audit[-1]["metadata"]
    assert metadata["from"] == "free"
    assert metadata["to"] == "pro"


# ── computed fields ──────────────────────────────────────────────────────────


async def test_a_future_suspension_reads_as_banned(rows):
    rows["row"]["banned_until"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    user = await users.get_user("user-1")
    assert user.is_banned is True


async def test_a_lapsed_suspension_does_not_read_as_banned(rows):
    rows["row"]["banned_until"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    user = await users.get_user("user-1")
    assert user.is_banned is False


async def test_the_admin_row_is_flagged(rows, admin_emails):
    rows["row"]["email"] = admin_emails

    user = await users.get_user("user-1")
    assert user.is_admin is True


# ── moderation orchestration ─────────────────────────────────────────────────


async def test_a_post_is_snapshotted_before_it_is_deleted(monkeypatch, silence_audit):
    """
    A post delete cascades its comments and votes away, so the snapshot has to
    be taken first — afterwards there is nothing left to describe.
    """
    from models.community import Post, PostAuthor
    from services.community import posts as post_service

    order: list = []

    async def _get_post(post_id, viewer_id=None):
        order.append("read")
        return Post(
            id=post_id,
            type="thought",
            post_kind="text",
            title="A title",
            content="the body",
            score=3,
            comments_count=1,
            is_edited=False,
            created_at=datetime.now(UTC),
            author=PostAuthor(id="author-1", full_name="Mira"),
        )

    async def _delete(*, post_id):
        order.append("delete")

    monkeypatch.setattr(post_service, "get_post", _get_post)
    monkeypatch.setattr(post_service, "delete_post_as_moderator", _delete)

    await moderation.delete_post(post_id="post-1", actor=ACTOR, reason="spam")

    assert order == ["read", "delete"]
    entry = silence_audit[-1]
    assert entry["reason"] == "spam"
    assert entry["metadata"]["title"] == "A title"
    assert entry["metadata"]["author_name"] == "Mira"


async def test_a_missing_post_becomes_an_admin_not_found(monkeypatch):
    """
    A `CommunityError` must not escape into the admin router, or every community
    error type becomes part of the admin router's contract.
    """
    from services.community import posts as post_service
    from services.community.errors import NotFound as CommunityNotFound

    async def _get_post(post_id, viewer_id=None):
        raise CommunityNotFound("post ghost does not exist")

    monkeypatch.setattr(post_service, "get_post", _get_post)

    with pytest.raises(NotFound):
        await moderation.delete_post(post_id="ghost", actor=ACTOR)


async def test_a_failed_audit_write_does_not_fail_the_request(monkeypatch):
    """
    The delete already happened. A 502 here would make the admin click delete
    again — on whatever the list has re-sorted into that position.
    """

    async def _boom(operation, *, what):
        raise RuntimeError("supabase is down")

    monkeypatch.setattr(audit._db, "table_op", _boom)

    await audit.record(actor=ACTOR, action="post.delete", target_type="post", target_id="post-1")
