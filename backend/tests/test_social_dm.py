"""
Tests for direct messages.

Two things carry the weight here and both are tested against behaviour rather
than against the shape of a mock:

  * **Eligibility.** The rules are configurable precisely so they can be relaxed
    for testing, which means a bug that relaxes them by accident would look like
    a passing test suite. Every rule is asserted both ways round — on when it
    should refuse, and off when it should not.
  * **Participation.** The backend holds the service-role key and bypasses row
    level security, so `require_participant` is the only thing between one
    member and somebody else's private messages. A third party is asserted to be
    refused on read *and* on write, not just on one of them.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from config import settings
from dependencies.auth import AuthUser, get_current_user
from dependencies.rate_limit import UserRateLimit
from services import db as db_module
from services import profile_service
from services.social import activity, blocks, conversations, eligibility, messages
from services.social.errors import (
    InvalidRequest,
    NotAParticipant,
    NotEligible,
    NotFound,
    UpstreamFailure,
)

# ═══════════════════════════════════════════════════════════════════════════════
# A fake Supabase that actually filters
# ═══════════════════════════════════════════════════════════════════════════════
# Rows are stored and the operators are applied for real, so a query that
# forgets an `.eq` fails the test instead of quietly matching everything. That
# matters most for `require_participant`, whose whole job is one comparison.


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    def __init__(self, db: "FakeDB", table: str) -> None:
        self._db = db
        self._table = table
        self._filters: list = []
        self._order: Optional[tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._mode = "select"
        self._payload: Any = None
        self._on_conflict: Optional[str] = None

    # -- builders ------------------------------------------------------------
    def select(self, _columns: str = "*") -> "_Query":
        self._mode = "select"
        return self

    def insert(self, payload: dict) -> "_Query":
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: dict, on_conflict: Optional[str] = None) -> "_Query":
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def delete(self) -> "_Query":
        self._mode = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append(lambda row: row.get(column) == value)
        return self

    def in_(self, column: str, values: list) -> "_Query":
        self._filters.append(lambda row: row.get(column) in values)
        return self

    def lt(self, column: str, value: Any) -> "_Query":
        self._filters.append(lambda row: str(row.get(column)) < str(value))
        return self

    def order(self, column: str, desc: bool = False) -> "_Query":
        self._order = (column, desc)
        return self

    def limit(self, count: int) -> "_Query":
        self._limit = count
        return self

    # -- execution -----------------------------------------------------------
    def _matches(self, row: dict) -> bool:
        return all(predicate(row) for predicate in self._filters)

    def execute(self) -> _Result:
        rows = self._db.tables.setdefault(self._table, [])

        if self._mode == "insert":
            self._db.raise_if_armed(self._table)
            record = dict(self._payload)
            record.setdefault("id", f"{self._table}-{len(rows) + 1}")
            record.setdefault("created_at", datetime.now(UTC).isoformat())
            self._db.enforce_unique(self._table, record)
            rows.append(record)
            return _Result([record])

        if self._mode == "upsert":
            record = dict(self._payload)
            keys = [k.strip() for k in (self._on_conflict or "id").split(",")]
            for existing in rows:
                if all(existing.get(k) == record.get(k) for k in keys):
                    existing.update(record)
                    return _Result([existing])
            record.setdefault("created_at", datetime.now(UTC).isoformat())
            rows.append(record)
            return _Result([record])

        if self._mode == "delete":
            removed = [row for row in rows if self._matches(row)]
            self._db.tables[self._table] = [row for row in rows if not self._matches(row)]
            return _Result(removed)

        found = [row for row in rows if self._matches(row)]
        if self._order:
            column, desc = self._order
            found.sort(key=lambda row: str(row.get(column) or ""), reverse=desc)
        if self._limit is not None:
            found = found[: self._limit]
        return _Result(found)


class _Rpc:
    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> _Result:
        return _Result(self._result)


class FakeDB:
    """In-memory stand-in for the Supabase client `services.db` reaches for."""

    def __init__(
        self,
        tables: Optional[dict] = None,
        rpcs: Optional[dict] = None,
        unique: Optional[dict] = None,
    ) -> None:
        self.tables: dict[str, list[dict]] = tables or {}
        self.rpcs: dict[str, Any] = rpcs or {}
        # {table: (col, col)} — the pair index 013 relies on.
        self.unique: dict[str, tuple] = unique or {}
        self._armed_failure: Optional[str] = None

    def arm_insert_failure(self, table: str) -> None:
        """Make the next insert into `table` fail as a duplicate key."""
        self._armed_failure = table

    def raise_if_armed(self, table: str) -> None:
        if self._armed_failure == table:
            self._armed_failure = None
            raise RuntimeError('duplicate key value violates unique constraint "..." (23505)')

    def enforce_unique(self, table: str, record: dict) -> None:
        columns = self.unique.get(table)
        if not columns:
            return
        for row in self.tables.get(table, []):
            if all(row.get(c) == record.get(c) for c in columns):
                raise RuntimeError("duplicate key value violates unique constraint (23505)")

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict) -> _Rpc:
        handler = self.rpcs.get(name)
        if callable(handler):
            return _Rpc(handler(params))
        return _Rpc(handler if handler is not None else [])


def install(monkeypatch, db: FakeDB) -> None:
    """`services.db.SupabaseOps` resolves the client per call, so one patch does it."""
    monkeypatch.setattr(db_module, "get_supabase", lambda: db)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

ALICE = "aaaaaaaa-0000-0000-0000-000000000001"
BOB = "bbbbbbbb-0000-0000-0000-000000000002"
CAROL = "cccccccc-0000-0000-0000-000000000003"


def user(
    user_id: str = ALICE,
    *,
    email_verified: bool = True,
    phone_verified: bool = True,
    age_days: int = 365,
) -> AuthUser:
    return AuthUser(
        id=user_id,
        email="someone@example.com",
        email_verified=email_verified,
        phone_verified=phone_verified,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


@pytest.fixture(autouse=True)
def permissive_rules(monkeypatch):
    """
    Default to rules that pass, so each test turns on only the one it is about.

    Without this every test would have to satisfy all three rules incidentally,
    and a test named after blocking would fail for an unrelated reason.
    """
    monkeypatch.setattr(settings, "DM_REQUIRE_EMAIL_VERIFIED", False)
    monkeypatch.setattr(settings, "DM_REQUIRE_PHONE_VERIFIED", False)
    monkeypatch.setattr(settings, "DM_MIN_ACCOUNT_AGE_DAYS", 0)


def seeded_db(**overrides) -> FakeDB:
    tables = {
        "profiles": [{"id": ALICE}, {"id": BOB}, {"id": CAROL}],
        "dm_conversations": [],
        "dm_messages": [],
        "dm_reads": [],
        "dm_blocks": [],
        "user_settings": [],
    }
    tables.update(overrides)
    return FakeDB(tables=tables, unique={"dm_conversations": ("user_a", "user_b")})


# ═══════════════════════════════════════════════════════════════════════════════
# Eligibility — the account rules
# ═══════════════════════════════════════════════════════════════════════════════


def test_email_rule_refuses_only_when_it_is_switched_on(monkeypatch):
    unverified = user(email_verified=False)

    monkeypatch.setattr(settings, "DM_REQUIRE_EMAIL_VERIFIED", False)
    assert eligibility.check_sender(unverified).can_send

    monkeypatch.setattr(settings, "DM_REQUIRE_EMAIL_VERIFIED", True)
    verdict = eligibility.check_sender(unverified)
    assert not verdict.can_send
    assert verdict.reasons == (eligibility.EMAIL_UNVERIFIED,)


def test_phone_rule_refuses_only_when_it_is_switched_on(monkeypatch):
    """
    The default is off, and that default is load-bearing: no Supabase project
    here has an SMS provider, so `phone_confirmed_at` is NULL for everyone and
    turning this on refuses every account.
    """
    unverified = user(phone_verified=False)

    monkeypatch.setattr(settings, "DM_REQUIRE_PHONE_VERIFIED", False)
    assert eligibility.check_sender(unverified).can_send

    monkeypatch.setattr(settings, "DM_REQUIRE_PHONE_VERIFIED", True)
    verdict = eligibility.check_sender(unverified)
    assert not verdict.can_send
    assert verdict.reasons == (eligibility.PHONE_UNVERIFIED,)


@pytest.mark.parametrize("age_days,allowed", [(89, False), (90, True), (400, True)])
def test_account_age_is_measured_against_the_configured_threshold(monkeypatch, age_days, allowed):
    monkeypatch.setattr(settings, "DM_MIN_ACCOUNT_AGE_DAYS", 90)
    verdict = eligibility.check_sender(user(age_days=age_days))
    assert verdict.can_send is allowed
    if not allowed:
        assert eligibility.ACCOUNT_TOO_NEW in verdict.reasons


def test_a_missing_creation_date_fails_closed_while_the_age_rule_is_on(monkeypatch):
    """
    Failing open here would turn any change in GoTrue's response shape into a
    silently disabled anti-abuse rule — the one failure mode that must be loud.
    """
    monkeypatch.setattr(settings, "DM_MIN_ACCOUNT_AGE_DAYS", 90)
    undated = AuthUser(id=ALICE, email_verified=True, phone_verified=True, created_at=None)
    assert eligibility.ACCOUNT_TOO_NEW in eligibility.check_sender(undated).reasons


def test_a_missing_creation_date_is_harmless_once_the_age_rule_is_off(monkeypatch):
    monkeypatch.setattr(settings, "DM_MIN_ACCOUNT_AGE_DAYS", 0)
    undated = AuthUser(id=ALICE, email_verified=True, phone_verified=True, created_at=None)
    assert eligibility.check_sender(undated).can_send


def test_every_unmet_rule_is_reported_at_once(monkeypatch):
    """One round trip per obstacle would make the checklist useless."""
    monkeypatch.setattr(settings, "DM_REQUIRE_EMAIL_VERIFIED", True)
    monkeypatch.setattr(settings, "DM_REQUIRE_PHONE_VERIFIED", True)
    monkeypatch.setattr(settings, "DM_MIN_ACCOUNT_AGE_DAYS", 90)

    verdict = eligibility.check_sender(user(email_verified=False, phone_verified=False, age_days=1))
    assert set(verdict.reasons) == {
        eligibility.EMAIL_UNVERIFIED,
        eligibility.PHONE_UNVERIFIED,
        eligibility.ACCOUNT_TOO_NEW,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Eligibility — the pair rules
# ═══════════════════════════════════════════════════════════════════════════════


def test_a_recipient_who_blocked_you_refuses_the_pairing(monkeypatch):
    db = seeded_db(dm_blocks=[{"blocker_id": BOB, "blocked_id": ALICE}])
    install(monkeypatch, db)

    verdict = asyncio.run(eligibility.check_pair(user(ALICE), BOB))
    assert not verdict.can_send
    assert eligibility.RECIPIENT_BLOCKED_YOU in verdict.reasons


def test_blocking_someone_also_stops_you_messaging_them(monkeypatch):
    """A block is one-directional in storage and two-directional in effect."""
    db = seeded_db(dm_blocks=[{"blocker_id": ALICE, "blocked_id": BOB}])
    install(monkeypatch, db)

    verdict = asyncio.run(eligibility.check_pair(user(ALICE), BOB))
    assert not verdict.can_send
    assert eligibility.YOU_BLOCKED_RECIPIENT in verdict.reasons


def test_an_unrelated_block_does_not_leak_across_pairs(monkeypatch):
    """Carol blocking Bob must not stop Alice reaching Bob."""
    db = seeded_db(dm_blocks=[{"blocker_id": CAROL, "blocked_id": BOB}])
    install(monkeypatch, db)

    assert asyncio.run(eligibility.check_pair(user(ALICE), BOB)).can_send


def test_a_recipient_who_turned_dms_off_refuses_the_pairing(monkeypatch):
    db = seeded_db(user_settings=[{"user_id": BOB, "dm_enabled": False}])
    install(monkeypatch, db)

    verdict = asyncio.run(eligibility.check_pair(user(ALICE), BOB))
    assert eligibility.RECIPIENT_DISABLED_DMS in verdict.reasons


def test_a_member_with_no_settings_row_still_accepts_messages(monkeypatch):
    """
    `get_user_settings` only writes a row on first read, so an account that has
    never opened Settings must not read as having opted out.
    """
    db = seeded_db(user_settings=[])
    install(monkeypatch, db)

    assert asyncio.run(eligibility.accepts_messages(BOB)) is True


def test_you_cannot_message_yourself(monkeypatch):
    install(monkeypatch, seeded_db())
    verdict = asyncio.run(eligibility.check_pair(user(ALICE), ALICE))
    assert eligibility.CANNOT_MESSAGE_YOURSELF in verdict.reasons


# ═══════════════════════════════════════════════════════════════════════════════
# Conversations
# ═══════════════════════════════════════════════════════════════════════════════


def test_the_pair_is_stored_in_a_canonical_order():
    assert conversations._ordered(BOB, ALICE) == (ALICE, BOB)
    assert conversations._ordered(ALICE, BOB) == (ALICE, BOB)


def test_opening_a_thread_from_either_side_yields_the_same_conversation(monkeypatch):
    """
    The whole reason `user_a < user_b` exists. Without it each side creates its
    own row and neither can see what the other wrote.
    """
    db = seeded_db()
    install(monkeypatch, db)

    first = asyncio.run(conversations.get_or_create(user(ALICE), BOB))
    second = asyncio.run(conversations.get_or_create(user(BOB), ALICE))

    assert first["id"] == second["id"]
    assert len(db.tables["dm_conversations"]) == 1


def test_a_lost_insert_race_re_reads_instead_of_failing(monkeypatch):
    """
    Two people opening the same thread in the same instant both pass the SELECT.
    The unique index turns the second INSERT into a duplicate-key error, and
    re-reading is the whole fix.
    """
    db = seeded_db()
    install(monkeypatch, db)

    # Simulate the other side having won: the row exists, and our insert fails.
    user_a, user_b = conversations._ordered(ALICE, BOB)
    db.tables["dm_conversations"].append({"id": "existing", "user_a": user_a, "user_b": user_b})
    db.arm_insert_failure("dm_conversations")

    # Force the SELECT to miss the way it would have before the other side
    # committed, by pointing get_or_create at a table state it cannot see.
    original_find = conversations._find
    calls = {"n": 0}

    async def find_once_empty(a, b):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await original_find(a, b)

    monkeypatch.setattr(conversations, "_find", find_once_empty)

    result = asyncio.run(conversations.get_or_create(user(ALICE), BOB))
    assert result["id"] == "existing"


def test_opening_a_thread_with_someone_who_does_not_exist_is_a_404(monkeypatch):
    install(monkeypatch, seeded_db())
    with pytest.raises(NotFound):
        asyncio.run(conversations.get_or_create(user(ALICE), "nobody"))


def test_opening_a_thread_is_refused_when_the_gate_says_no(monkeypatch):
    db = seeded_db(dm_blocks=[{"blocker_id": BOB, "blocked_id": ALICE}])
    install(monkeypatch, db)

    with pytest.raises(NotEligible) as caught:
        asyncio.run(conversations.get_or_create(user(ALICE), BOB))
    assert eligibility.RECIPIENT_BLOCKED_YOU in caught.value.reasons


def test_a_third_party_is_not_a_participant(monkeypatch):
    db = seeded_db(dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}])
    install(monkeypatch, db)

    assert asyncio.run(conversations.require_participant("c1", ALICE))["id"] == "c1"
    with pytest.raises(NotAParticipant):
        asyncio.run(conversations.require_participant("c1", CAROL))


def test_peer_of_returns_the_other_side():
    conversation = {"user_a": ALICE, "user_b": BOB}
    assert conversations.peer_of(conversation, ALICE) == BOB
    assert conversations.peer_of(conversation, BOB) == ALICE


def test_the_inbox_is_shaped_for_the_list_and_survives_an_empty_thread(monkeypatch):
    db = seeded_db()
    db.rpcs["dm_inbox"] = [
        {
            "conversation_id": "c1",
            "peer_id": BOB,
            "peer_full_name": "Bob",
            "peer_avatar_url": None,
            "peer_subscription_plan": "pro",
            "last_body": "hey",
            "last_sender_id": BOB,
            "last_message_at": "2026-08-12T10:00:00+00:00",
            "unread_count": 2,
        },
        {
            "conversation_id": "c2",
            "peer_id": CAROL,
            "peer_full_name": "Carol",
            "peer_avatar_url": None,
            "peer_subscription_plan": None,
            "last_body": None,
            "last_sender_id": None,
            "last_message_at": None,
            "unread_count": 0,
        },
    ]
    install(monkeypatch, db)

    inbox = asyncio.run(conversations.list_inbox(ALICE))

    assert inbox[0]["peer"]["full_name"] == "Bob"
    assert inbox[0]["last_message"]["body"] == "hey"
    assert inbox[0]["unread_count"] == 2
    # A conversation opened but never written into has no preview, not an empty
    # bubble.
    assert inbox[1]["last_message"] is None


def test_unread_total_handles_both_scalar_rpc_shapes(monkeypatch):
    db = seeded_db()
    install(monkeypatch, db)

    db.rpcs["dm_unread_total"] = [{"dm_unread_total": 4}]
    assert asyncio.run(conversations.unread_total(ALICE)) == 4

    db.rpcs["dm_unread_total"] = [7]
    assert asyncio.run(conversations.unread_total(ALICE)) == 7

    db.rpcs["dm_unread_total"] = []
    assert asyncio.run(conversations.unread_total(ALICE)) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Messages
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
def test_an_empty_or_whitespace_only_message_is_refused(raw):
    """It renders as an empty bubble the recipient cannot distinguish from a bug."""
    with pytest.raises(InvalidRequest):
        messages.normalise_body(raw)


def test_a_message_over_the_cap_is_refused():
    with pytest.raises(InvalidRequest):
        messages.normalise_body("x" * (messages.MAX_BODY + 1))


def test_a_message_is_trimmed_before_it_is_stored():
    assert messages.normalise_body("  hello  ") == "hello"


def test_a_third_party_cannot_read_a_thread(monkeypatch):
    db = seeded_db(
        dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}],
        dm_messages=[{"id": "m1", "conversation_id": "c1", "sender_id": ALICE, "body": "private"}],
    )
    install(monkeypatch, db)

    with pytest.raises(NotAParticipant):
        asyncio.run(messages.list_messages("c1", CAROL))


def test_a_third_party_cannot_write_into_a_thread(monkeypatch):
    db = seeded_db(dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}])
    install(monkeypatch, db)

    with pytest.raises(NotAParticipant):
        asyncio.run(messages.send("c1", user(CAROL), "let me in"))
    assert db.tables["dm_messages"] == []


def test_sending_stores_the_message_and_advances_the_senders_cursor(monkeypatch):
    db = seeded_db(dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}])
    install(monkeypatch, db)

    stored = asyncio.run(messages.send("c1", user(ALICE), "  hello  "))

    assert stored["body"] == "hello"
    assert stored["sender_id"] == ALICE
    # The sender has by definition read their own thread; leaving their cursor
    # behind would light the nav badge for a thread they are typing in.
    cursors = [r for r in db.tables["dm_reads"] if r["user_id"] == ALICE]
    assert len(cursors) == 1


def test_sending_is_refused_when_the_peer_blocked_you_after_the_thread_opened(monkeypatch):
    """
    Standing is re-checked on send, not only when the thread was opened — the
    composer may have sat on screen for an hour.
    """
    db = seeded_db(
        dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}],
        dm_blocks=[{"blocker_id": BOB, "blocked_id": ALICE}],
    )
    install(monkeypatch, db)

    with pytest.raises(NotEligible):
        asyncio.run(messages.send("c1", user(ALICE), "still there?"))
    assert db.tables["dm_messages"] == []


def test_a_thread_is_returned_oldest_first(monkeypatch):
    db = seeded_db(
        dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}],
        dm_messages=[
            {"id": "m1", "conversation_id": "c1", "sender_id": ALICE, "created_at": "2026-01-01"},
            {"id": "m2", "conversation_id": "c1", "sender_id": BOB, "created_at": "2026-01-02"},
            {"id": "m3", "conversation_id": "c1", "sender_id": ALICE, "created_at": "2026-01-03"},
        ],
    )
    install(monkeypatch, db)

    page = asyncio.run(messages.list_messages("c1", ALICE))
    assert [row["id"] for row in page] == ["m1", "m2", "m3"]


def test_paging_backwards_excludes_what_was_already_seen(monkeypatch):
    db = seeded_db(
        dm_conversations=[{"id": "c1", "user_a": ALICE, "user_b": BOB}],
        dm_messages=[
            {"id": "m1", "conversation_id": "c1", "sender_id": ALICE, "created_at": "2026-01-01"},
            {"id": "m2", "conversation_id": "c1", "sender_id": BOB, "created_at": "2026-01-02"},
        ],
    )
    install(monkeypatch, db)

    page = asyncio.run(messages.list_messages("c1", ALICE, before="2026-01-02"))
    assert [row["id"] for row in page] == ["m1"]


def test_messages_from_another_conversation_are_not_included(monkeypatch):
    db = seeded_db(
        dm_conversations=[
            {"id": "c1", "user_a": ALICE, "user_b": BOB},
            {"id": "c2", "user_a": ALICE, "user_b": CAROL},
        ],
        dm_messages=[
            {"id": "m1", "conversation_id": "c1", "sender_id": ALICE, "created_at": "2026-01-01"},
            {"id": "m2", "conversation_id": "c2", "sender_id": CAROL, "created_at": "2026-01-02"},
        ],
    )
    install(monkeypatch, db)

    page = asyncio.run(messages.list_messages("c1", ALICE))
    assert [row["id"] for row in page] == ["m1"]


# ═══════════════════════════════════════════════════════════════════════════════
# Blocking
# ═══════════════════════════════════════════════════════════════════════════════


def test_blocking_is_idempotent(monkeypatch):
    db = seeded_db()
    install(monkeypatch, db)

    asyncio.run(blocks.block(ALICE, BOB))
    asyncio.run(blocks.block(ALICE, BOB))

    assert len(db.tables["dm_blocks"]) == 1


def test_unblocking_restores_the_pairing(monkeypatch):
    db = seeded_db()
    install(monkeypatch, db)

    asyncio.run(blocks.block(ALICE, BOB))
    assert not asyncio.run(eligibility.check_pair(user(ALICE), BOB)).can_send

    asyncio.run(blocks.unblock(ALICE, BOB))
    assert asyncio.run(eligibility.check_pair(user(ALICE), BOB)).can_send


def test_you_cannot_block_yourself(monkeypatch):
    install(monkeypatch, seeded_db())
    with pytest.raises(InvalidRequest):
        asyncio.run(blocks.block(ALICE, ALICE))


def test_unblocking_someone_who_is_not_blocked_is_a_no_op(monkeypatch):
    db = seeded_db()
    install(monkeypatch, db)
    asyncio.run(blocks.unblock(ALICE, BOB))
    assert db.tables["dm_blocks"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Activity
# ═══════════════════════════════════════════════════════════════════════════════


def test_activity_maps_the_rpc_row(monkeypatch):
    db = seeded_db()
    db.rpcs["community_user_activity"] = [
        {
            "post_count": 3,
            "comment_count": 11,
            "post_karma": 40,
            "comment_karma": 12,
            "total_karma": 52,
            "best_post_id": "p1",
            "best_post_title": "BTC",
            "best_post_score": 30,
        }
    ]
    install(monkeypatch, db)

    result = asyncio.run(activity.get_activity(ALICE))
    assert result["total_karma"] == 52
    assert result["best_post"] == {"id": "p1", "title": "BTC", "score": 30}


def test_a_member_who_never_posted_has_no_best_post(monkeypatch):
    """None, not a zero-scored card for a post that does not exist."""
    db = seeded_db()
    db.rpcs["community_user_activity"] = [
        {
            "post_count": 0,
            "comment_count": 0,
            "post_karma": 0,
            "comment_karma": 0,
            "total_karma": 0,
            "best_post_id": None,
            "best_post_title": None,
            "best_post_score": None,
        }
    ]
    install(monkeypatch, db)

    assert asyncio.run(activity.get_activity(ALICE))["best_post"] is None


def test_activity_degrades_to_zeroes_when_the_rpc_is_missing(monkeypatch):
    """
    On a project where 013 has not been run yet, the tab should render zeroes
    rather than an error — with a log line saying which happened.
    """

    def explode(params):
        raise RuntimeError("function community_user_activity(uuid) does not exist")

    db = seeded_db()
    db.rpcs["community_user_activity"] = explode
    install(monkeypatch, db)

    assert asyncio.run(activity.get_activity(ALICE)) == activity.EMPTY


# ═══════════════════════════════════════════════════════════════════════════════
# Per-account rate limiting
# ═══════════════════════════════════════════════════════════════════════════════


def _limited_app(limit: UserRateLimit, caller: AuthUser) -> TestClient:
    app = FastAPI()

    @app.post("/send", dependencies=[Depends(limit)])
    async def send() -> dict:
        return {"ok": True}

    app.dependency_overrides[get_current_user] = lambda: caller
    return TestClient(app)


def test_a_sender_over_their_budget_gets_429():
    limit = UserRateLimit(name="test-dm", limit=2, window_seconds=60)
    client = _limited_app(limit, user(ALICE))

    assert client.post("/send").status_code == 200
    assert client.post("/send").status_code == 200
    response = client.post("/send")
    assert response.status_code == 429
    assert response.headers["Retry-After"]


def test_each_account_has_its_own_budget():
    """
    The point of keying on the account rather than the address: two members
    behind one connection must not share a ceiling.
    """
    limit = UserRateLimit(name="test-dm-2", limit=1, window_seconds=60)

    assert _limited_app(limit, user(ALICE)).post("/send").status_code == 200
    assert _limited_app(limit, user(BOB)).post("/send").status_code == 200
    assert _limited_app(limit, user(ALICE)).post("/send").status_code == 429


def test_the_window_slides_so_a_throttled_sender_recovers(monkeypatch):
    limit = UserRateLimit(name="test-dm-3", limit=1, window_seconds=60)
    client = _limited_app(limit, user(ALICE))

    assert client.post("/send").status_code == 200
    assert client.post("/send").status_code == 429

    import time as time_module

    real = time_module.monotonic
    monkeypatch.setattr(time_module, "monotonic", lambda: real() + 61)
    assert client.post("/send").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# The allowlist trap
# ═══════════════════════════════════════════════════════════════════════════════


def test_dm_enabled_survives_the_user_settings_allowlist(monkeypatch):
    """
    Regression. `update_user_settings` filters its input against `allowed_fields`
    and returns success either way, so a settings column missing from that list
    looks like it saved and did not. Exactly how `bio` was silently dropped by
    the profile update before it was caught.
    """
    written: dict = {}

    class Recorder:
        def table(self, _name):
            return self

        def select(self, _columns):
            return self

        def eq(self, _column, _value):
            return self

        def update(self, payload):
            written.update(payload)
            return self

        def insert(self, payload):
            written.update(payload)
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "settings-1"}]})()

    monkeypatch.setattr(profile_service, "get_supabase", lambda: Recorder())

    ok = asyncio.run(profile_service.update_user_settings(ALICE, {"dm_enabled": False}))

    assert ok is True
    assert "dm_enabled" in written, "dm_enabled was dropped by the allowlist"
    assert written["dm_enabled"] is False


def test_an_unknown_settings_field_is_still_dropped(monkeypatch):
    """The allowlist must stay an allowlist — this is what makes the test above meaningful."""
    written: dict = {}

    class Recorder:
        def table(self, _name):
            return self

        def select(self, _columns):
            return self

        def eq(self, _column, _value):
            return self

        def update(self, payload):
            written.update(payload)
            return self

        def insert(self, payload):
            written.update(payload)
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "settings-1"}]})()

    monkeypatch.setattr(profile_service, "get_supabase", lambda: Recorder())

    asyncio.run(profile_service.update_user_settings(ALICE, {"is_admin": True}))
    assert "is_admin" not in written


# ═══════════════════════════════════════════════════════════════════════════════
# Upstream failures
# ═══════════════════════════════════════════════════════════════════════════════


def test_a_database_failure_on_send_raises_rather_than_reporting_success(monkeypatch):
    """A failed write must not come back as a 200 with a cleared composer."""

    class Broken(FakeDB):
        def table(self, name):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(db_module, "get_supabase", lambda: Broken())

    with pytest.raises(UpstreamFailure):
        asyncio.run(messages.list_messages("c1", ALICE))
