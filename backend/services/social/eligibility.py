"""
Who may send a direct message.

One gate, checked in one place, for a feature whose whole risk is that an open
inbox invites abuse. It answers in two halves:

    account_reasons()  rules about the sender alone — verified email, verified
                       phone, account age. Pure, so the matrix is cheap to test.
    check_pair()       rules about the two people — blocking, and the
                       recipient's account-wide opt-out. Needs the database.

Both return *machine-readable* reasons rather than a prose message. The UI turns
them into a checklist naming the requirement that is unmet; a flat "you cannot
message people" would leave someone with no idea whether to wait a month or
verify an address.

Reading a thread and replying inside one are never gated. The rules exist to
stop a fresh throwaway account from spraying strangers, not to trap somebody
mid-conversation — so they are evaluated when a conversation is *opened* and
when a message is sent, against the sender, and never against the reader.

The thresholds live in `config.settings` rather than here. At their intended
values a young project has nobody who qualifies, so the feature could not be
exercised at all without a way to relax them; see the DM_* block in config.py.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from config import settings
from dependencies.auth import AuthUser

from . import _db

# Reason codes. The frontend switches on these strings, so they are part of the
# API contract — rename one and `EligibilityNotice` silently loses a row.
EMAIL_UNVERIFIED = "email_unverified"
PHONE_UNVERIFIED = "phone_unverified"
ACCOUNT_TOO_NEW = "account_too_new"
RECIPIENT_BLOCKED_YOU = "recipient_blocked_you"
YOU_BLOCKED_RECIPIENT = "you_blocked_recipient"
RECIPIENT_DISABLED_DMS = "recipient_disabled_dms"
CANNOT_MESSAGE_YOURSELF = "cannot_message_yourself"


@dataclass(frozen=True)
class Requirements:
    """What the server currently demands, so the UI can render the rules."""

    email_verified: bool
    phone_verified: bool
    min_account_age_days: int


@dataclass(frozen=True)
class Eligibility:
    """`can_send` is `not reasons`; both are carried so the API shape is explicit."""

    can_send: bool
    reasons: tuple[str, ...]

    @classmethod
    def of(cls, reasons: tuple[str, ...]) -> "Eligibility":
        return cls(can_send=not reasons, reasons=reasons)


def current_requirements() -> Requirements:
    return Requirements(
        email_verified=settings.DM_REQUIRE_EMAIL_VERIFIED,
        phone_verified=settings.DM_REQUIRE_PHONE_VERIFIED,
        min_account_age_days=settings.DM_MIN_ACCOUNT_AGE_DAYS,
    )


def account_reasons(user: AuthUser, *, now: Optional[datetime] = None) -> tuple[str, ...]:
    """
    The sender-only rules. Pure — `now` is injectable so age is testable.

    Order matters only for presentation: the checklist reads email, phone, age.
    """
    reasons: list[str] = []
    required = current_requirements()

    if required.email_verified and not user.email_verified:
        reasons.append(EMAIL_UNVERIFIED)

    if required.phone_verified and not user.phone_verified:
        reasons.append(PHONE_UNVERIFIED)

    if required.min_account_age_days > 0:
        moment = now or datetime.now(UTC)
        # No creation date and an age requirement in force is treated as too
        # new. Failing open here would turn any change in GoTrue's response
        # shape into a silently disabled anti-abuse rule — the one failure mode
        # that must not be quiet. When the requirement is 0 the branch is not
        # entered at all, so a missing date never blocks a project that has
        # deliberately turned the rule off.
        if user.created_at is None:
            reasons.append(ACCOUNT_TOO_NEW)
        else:
            age_days = (moment - user.created_at).total_seconds() / 86400
            if age_days < required.min_account_age_days:
                reasons.append(ACCOUNT_TOO_NEW)

    return tuple(reasons)


def check_sender(user: AuthUser, *, now: Optional[datetime] = None) -> Eligibility:
    """Whether this account may start conversations at all, ignoring the peer."""
    return Eligibility.of(account_reasons(user, now=now))


async def check_pair(
    sender: AuthUser,
    recipient_id: str,
    *,
    now: Optional[datetime] = None,
) -> Eligibility:
    """
    The full gate: the sender's own standing plus this particular pairing.

    The pair rules are evaluated even when the account rules already failed, so
    the UI can show every obstacle at once instead of one per round trip.
    """
    reasons = list(account_reasons(sender, now=now))

    if recipient_id == sender.id:
        reasons.append(CANNOT_MESSAGE_YOURSELF)
        return Eligibility.of(tuple(reasons))

    blocked_by, blocked_them = await _block_directions(sender.id, recipient_id)
    if blocked_by:
        reasons.append(RECIPIENT_BLOCKED_YOU)
    if blocked_them:
        reasons.append(YOU_BLOCKED_RECIPIENT)

    if not await accepts_messages(recipient_id):
        reasons.append(RECIPIENT_DISABLED_DMS)

    return Eligibility.of(tuple(reasons))


async def _block_directions(sender_id: str, recipient_id: str) -> tuple[bool, bool]:
    """
    (recipient blocked sender, sender blocked recipient).

    Both rows are fetched in one query rather than two: the pair is small and
    two round trips to answer one question is a waste on the send path.
    """
    rows = await _db.table_op(
        lambda client: (
            client.table("dm_blocks")
            .select("blocker_id, blocked_id")
            .in_("blocker_id", [sender_id, recipient_id])
            .in_("blocked_id", [sender_id, recipient_id])
            .execute()
        ),
        what="read block pair",
    )

    blocked_by = False
    blocked_them = False
    for row in rows or []:
        if row.get("blocker_id") == recipient_id and row.get("blocked_id") == sender_id:
            blocked_by = True
        if row.get("blocker_id") == sender_id and row.get("blocked_id") == recipient_id:
            blocked_them = True
    return blocked_by, blocked_them


async def accepts_messages(user_id: str) -> bool:
    """
    Whether `user_id` has left their inbox open.

    Defaults to True when there is no settings row: `dm_enabled` defaults TRUE in
    the schema and `get_user_settings` only writes a row on first read, so an
    account that has never opened Settings must not read as having opted out.
    """
    rows = await _db.table_op(
        lambda client: (
            client.table("user_settings")
            .select("dm_enabled")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        ),
        what="read dm_enabled",
    )
    if not rows:
        return True
    value = rows[0].get("dm_enabled")
    return True if value is None else bool(value)
