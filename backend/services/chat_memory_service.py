"""
What the assistant remembers about a user between sessions.

A conversation carries its own history; this carries the handful of facts that
are true across conversations — that someone trades futures rather than spot,
that they hold a position they keep asking about, that they want short answers.
Without it every session starts by learning the same things again.

Two decisions worth stating, because both were the other way in an earlier
sketch:

**Not built on `services/ai_notes.py`.** That module looks like a memory and is
not: it is a cache of *generated* notes keyed by a fingerprint of market facts,
shared across every user, and it makes its own LLM calls. Building per-user
preferences on it would have meant one user's stated position reaching another
user's prompt.

**Recall ships before writes.** Reading is a prompt block; writing is a model
deciding what is true about a person and storing it. The write path is
constrained hard — a fixed key allowlist, a length cap, and a refusal to write
anything that came out of untrusted content — and even so it is the half worth
being slow about.
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# What may be remembered, and nothing else. An open key space would let a model
# invent a schema over time, and a memory nobody can enumerate is a memory
# nobody can audit or correct.
ALLOWED_KEYS = {
    "holds": "positions the user has said they hold",
    "watching": "assets the user follows closely",
    "style": "how the user wants answers shaped",
    "horizon": "the timeframe the user trades on",
    "risk": "how the user has described their risk tolerance",
    "avoid": "topics or assets the user does not want raised",
}

# A remembered fact is a clause, not an essay. The cap is also what stops a
# scraped page from being laundered into the prompt through the memory.
MAX_VALUE_CHARS = 160
MAX_ENTRIES = len(ALLOWED_KEYS)

# Anything that looks like markup, a link, or an instruction is refused rather
# than stored. Memory is the one block that survives a session, so a prompt
# injection landing here would outlive the turn that carried it.
_REFUSED = re.compile(
    r"https?://|<[^>]+>|ignore (?:all |the )?(?:previous|above)|system prompt|<<<",
    re.IGNORECASE,
)


def _clean(value: str) -> Optional[str]:
    """A storable value, or None if it should not be stored at all."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text or _REFUSED.search(text):
        return None
    return text[:MAX_VALUE_CHARS]


async def recall(user_id: Optional[str]) -> Dict[str, str]:
    """Everything remembered about this user. Empty for an anonymous turn."""
    if not user_id:
        return {}

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        return {}

    try:
        rows = (
            client.table("chat_memory")
            .select("key, value")
            .eq("user_id", user_id)
            .limit(MAX_ENTRIES)
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001 — memory is never worth failing a turn
        logger.info("Chat memory unavailable: %s", e)
        return {}

    return {
        row["key"]: row["value"]
        for row in rows
        if row.get("key") in ALLOWED_KEYS and row.get("value")
    }


async def remember(user_id: Optional[str], updates: Dict[str, str]) -> List[str]:
    """
    Store what the turn concluded is worth keeping. Returns the keys written.

    Every value has been through `_clean`, and every key has to be in
    `ALLOWED_KEYS`. Nothing else is written, and nothing is written at all for
    an anonymous turn — there is no one to remember it about.
    """
    if not user_id or not isinstance(updates, dict):
        return []

    rows = []
    for key, value in updates.items():
        if key not in ALLOWED_KEYS:
            continue
        cleaned = _clean(value)
        if cleaned:
            rows.append({"user_id": user_id, "key": key, "value": cleaned})

    if not rows:
        return []

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        return []

    try:
        client.table("chat_memory").upsert(rows, on_conflict="user_id,key").execute()
    except Exception as e:  # noqa: BLE001
        logger.info("Chat memory write failed: %s", e)
        return []

    return [row["key"] for row in rows]


def describe(memory: Dict[str, str]) -> str:
    """
    Memory as a prompt block.

    Framed as reported preference rather than as fact: the user said this once,
    possibly weeks ago, and an answer that treats a remembered position as a
    current one is exactly the failure the whole source-precedence ladder exists
    to prevent.
    """
    if not memory:
        return ""
    lines = [
        "WHAT THE USER HAS TOLD YOU BEFORE",
        "Stated in an earlier session, not measured and possibly out of date. "
        "Use it to shape the answer, never as evidence about the market.",
    ]
    lines.extend(f"- {ALLOWED_KEYS.get(key, key)}: {value}" for key, value in memory.items())
    return "\n".join(lines)
