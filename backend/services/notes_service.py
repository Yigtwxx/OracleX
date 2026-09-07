"""
User notes, per user.

They used to live in a single `backend/data/user_notes.json` with no `user_id`
anywhere, and `routers/analysis.py` exposed all three endpoints with no auth
dependency — so every visitor, signed in or not, read and deleted every
account's notes. This is the same failure `services/watchlist_service.py`
records in its own docstring, in the same shape, left behind when that one was
fixed.

Storage is the `notes` table, which has been in the schema since migration 001
with a `user_id`, RLS policies and an index, and which nothing ever used. The
backend holds the service-role key and bypasses RLS, so the `user_id` filter in
each query here is the authorisation, not a convenience.

The JSON file is not read on any request path. `import_legacy_file` exists for
an operator who decides to hand the old notes to one account, because the old
store has no user to attribute them to.
"""

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# The pre-migration store. Read only by `import_legacy_file`, never on a
# request path — see the module docstring.
LEGACY_DATA_FILE = "data/user_notes.json"

# Bounds on what one account can write. Not a security boundary — the ownership
# filter is — but the endpoint takes free text and the row is read back on every
# poll of the Analysis tab.
MAX_NOTES_PER_USER = 200
MAX_TITLE_LENGTH = 200
MAX_CONTENT_LENGTH = 10_000


def _load_legacy() -> List[Dict]:
    if not os.path.exists(LEGACY_DATA_FILE):
        return []
    try:
        with open(LEGACY_DATA_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _row_to_note(row: Dict[str, Any]) -> Dict[str, str]:
    """
    One row in the shape the UI has always been given.

    The column is `created_at` and the client reads `date`; renaming it here
    rather than in the component keeps the change to this endpoint invisible to
    everything that already consumes it.
    """
    return {
        "id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "content": str(row.get("content") or ""),
        "date": str(row.get("created_at") or ""),
    }


def _client():
    from services.supabase_service import get_supabase

    return get_supabase()


async def get_notes(user_id: str) -> List[Dict[str, str]]:
    """This user's notes, newest first."""
    if not user_id:
        return []

    client = _client()
    if client is None:
        logger.warning("Supabase is not configured; notes are unavailable")
        return []

    rows = (
        client.table("notes")
        .select("id, title, content, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(MAX_NOTES_PER_USER)
        .execute()
    ).data or []

    return [_row_to_note(row) for row in rows]


async def create_note(user_id: str, title: str, content: str) -> List[Dict[str, str]]:
    """Create a note owned by `user_id` and return the caller's list."""
    if not user_id:
        raise PermissionError("a note needs an owner")

    client = _client()
    if client is None:
        raise RuntimeError("Supabase is not configured")

    # Trimmed before the insert rather than after the read, so the column never
    # comes to hold more than this code will hand back.
    created = (
        client.table("notes")
        .insert(
            {
                "user_id": user_id,
                "title": (title or "").strip()[:MAX_TITLE_LENGTH] or "Note",
                "content": (content or "").strip()[:MAX_CONTENT_LENGTH],
            }
        )
        .execute()
    ).data
    if not created:
        raise RuntimeError("the note could not be created")

    return await get_notes(user_id)


async def delete_note(user_id: str, note_id: str) -> List[Dict[str, str]]:
    """
    Delete one of this user's notes and return what is left.

    The `user_id` filter is the deletion's authorisation: the service-role key
    bypasses RLS, so a delete without it would take any note whose id was
    guessed.
    """
    if not user_id:
        raise PermissionError("a note needs an owner")

    client = _client()
    if client is None:
        raise RuntimeError("Supabase is not configured")

    client.table("notes").delete().eq("id", note_id).eq("user_id", user_id).execute()
    return await get_notes(user_id)


async def import_legacy_file(user_id: str) -> Dict[str, int]:
    """
    Hand the pre-migration `data/user_notes.json` notes to one account.

    Not called from anywhere: the old store has no user to attribute its notes
    to, so which account should receive them is a decision an operator makes,
    not one this module can infer. Run it from a shell when that decision has
    been made.
    """
    legacy = _load_legacy()
    imported = 0
    for entry in legacy[:MAX_NOTES_PER_USER]:
        if not isinstance(entry, dict):
            continue
        await create_note(user_id, entry.get("title") or "Imported", entry.get("content") or "")
        imported += 1
    return {"imported": imported, "found": len(legacy)}
