"""
The admin action trail.

Worth keeping even with a single admin. `banned_until` and `subscription_plan`
are overwritten in place, so without a row here the previous value is
unrecoverable; and a post delete is a hard delete that takes its comments and
votes with it, so this table's `metadata` snapshot is the only surviving record
of what was removed.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from models.admin import AuditEntry
from services.supabase_service import get_supabase

from . import _db

logger = logging.getLogger(__name__)

TABLE = "admin_audit_log"


@dataclass(frozen=True)
class AuditActor:
    """Whoever performed the action, taken from the verified token."""

    id: str
    email: Optional[str] = None


async def record(
    *,
    actor: AuditActor,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Append an entry. **Never raises.**

    The mutation it describes has already happened. Turning a failed log write
    into a failed request would tell the admin their delete did not work, and
    the natural response to that is to click delete again — on whatever the list
    has re-sorted into that position.
    """
    row = {
        "actor_id": actor.id,
        "actor_email": actor.email,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "reason": reason,
        "metadata": metadata or {},
    }
    try:
        await _db.table_op(
            lambda client: client.table(TABLE).insert(row).execute(),
            what="write audit entry",
        )
    except Exception as exc:
        logger.error("admin: audit write failed for %s on %s: %s", action, target_id, exc)


async def list_entries(
    *,
    limit: int = 50,
    offset: int = 0,
    target_type: Optional[str] = None,
) -> Tuple[list, int]:
    """The newest entries first, with the unpaginated total."""

    def _call(client: Any) -> Any:
        query = client.table(TABLE).select("*", count="exact")
        if target_type:
            query = query.eq("target_type", target_type)
        return query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    # `run` rather than `table_op`: the total lives on the response object, not
    # in `.data`, and PostgREST only computes it when count="exact" is asked for.
    response = await _db.run(lambda: _call(get_supabase()), what="list audit entries")
    rows = getattr(response, "data", None) or []
    total = getattr(response, "count", None)
    return [_to_entry(row) for row in rows], total if total is not None else len(rows)


def _to_entry(row: dict) -> AuditEntry:
    return AuditEntry(
        id=str(row.get("id")),
        actor_id=row.get("actor_id"),
        actor_email=row.get("actor_email"),
        action=row.get("action") or "",
        target_type=row.get("target_type") or "",
        target_id=row.get("target_id"),
        reason=row.get("reason"),
        metadata=row.get("metadata") or {},
        created_at=row.get("created_at"),
    )
