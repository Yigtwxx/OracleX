"""
Social service: direct messages, blocking, and a member's own community numbers.

Laid out like `services/community/`, one responsibility per module:

    eligibility    who may send a DM at all — verified email, verified phone,
                   account age, blocking, and the recipient's opt-out
    conversations  the inbox and opening a thread; owns the canonical pair order
    messages       reading a thread, sending into it, the read cursor
    blocks         per-person blocking
    activity       the Activity tab's counts and karma
    errors         the exception types the router turns into status codes
    _db            the asyncio.to_thread wrapper around the blocking client

The one rule worth restating: the backend holds the service-role key and
bypasses row-level security, so `conversations.require_participant` is the only
thing standing between one member and somebody else's private messages. Every
read and write of `dm_messages` goes through it.
"""

from . import activity, blocks, conversations, eligibility, messages
from .errors import (
    InvalidRequest,
    NotAParticipant,
    NotEligible,
    NotFound,
    SocialError,
    UpstreamFailure,
)

__all__ = [
    "activity",
    "blocks",
    "conversations",
    "eligibility",
    "messages",
    "InvalidRequest",
    "NotAParticipant",
    "NotEligible",
    "NotFound",
    "SocialError",
    "UpstreamFailure",
]
