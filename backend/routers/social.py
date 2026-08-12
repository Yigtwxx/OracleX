"""
Social Router — direct messages, blocking, and a member's own activity.

Every route here is authenticated; none of it is readable signed out. The caller
always comes from the verified JWT, and a `user_id` in a path or body is treated
as a *target*, never as an identity — the backend connects with the service-role
key and bypasses row-level security, so `conversations.require_participant` in
the service layer is the only thing keeping one member out of another's threads.

Sending is gated by `services.social.eligibility`. A refusal returns 403 with
the machine-readable reasons attached so the UI can name the requirement that is
unmet instead of a flat "no".
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from dependencies.auth import AuthUser, get_current_user
from dependencies.rate_limit import UserRateLimit
from config import settings
from services import social
from services.social import activity as activity_service
from services.social import blocks as block_service
from services.social import conversations as conversation_service
from services.social import eligibility as eligibility_service
from services.social import messages as message_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/social", tags=["social"])

# Per *account*, not per address: one person may only message so much, and
# keying that on IP would punish everyone behind a shared connection while
# handing a free reset to anyone who changes network.
_send_limit = UserRateLimit(
    name="dm-send",
    limit=settings.DM_DAILY_SEND_LIMIT,
    window_seconds=24 * 60 * 60,
    detail="You have sent too many messages today. Try again tomorrow.",
)


class StartConversationRequest(BaseModel):
    user_id: str


class SendMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=message_service.MAX_BODY)


def _http_error(exc: social.SocialError) -> HTTPException:
    """Map a service error onto a status code. The only place that knows both."""
    if isinstance(exc, social.NotEligible):
        # 403 with the reasons in the body. The frontend renders them as a
        # checklist; a bare 403 would leave the user unable to tell whether to
        # verify something or simply wait.
        return HTTPException(
            status_code=403,
            detail={"message": "You cannot message this person yet.", "reasons": list(exc.reasons)},
        )
    if isinstance(exc, social.NotAParticipant):
        return HTTPException(status_code=403, detail="This conversation is not yours.")
    if isinstance(exc, social.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, social.InvalidRequest):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail="Messages are unavailable right now.")


# ═══════════════════════════════════════════════════════════════════════════════
# ELIGIBILITY
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/eligibility")
async def read_eligibility(user: AuthUser = Depends(get_current_user)):
    """
    Whether this account may start conversations, and what the rules are.

    Returns the requirements as well as the verdict so the UI can show the full
    checklist — including the rules the caller already satisfies.
    """
    verdict = eligibility_service.check_sender(user)
    required = eligibility_service.current_requirements()
    return {
        "can_send": verdict.can_send,
        "reasons": list(verdict.reasons),
        "requirements": {
            "email_verified": required.email_verified,
            "phone_verified": required.phone_verified,
            "min_account_age_days": required.min_account_age_days,
        },
        "status": {
            "email_verified": user.email_verified,
            "phone_verified": user.phone_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/conversations")
async def list_conversations(user: AuthUser = Depends(get_current_user)):
    try:
        return {"conversations": await conversation_service.list_inbox(user.id)}
    except social.SocialError as exc:
        raise _http_error(exc) from exc


@router.post("/conversations", status_code=201)
async def start_conversation(
    data: StartConversationRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Open (or return) the thread with another member."""
    try:
        conversation = await conversation_service.get_or_create(user, data.user_id)
    except social.SocialError as exc:
        raise _http_error(exc) from exc
    return {
        "id": conversation["id"],
        "peer_id": conversation_service.peer_of(conversation, user.id),
    }


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    before: Optional[str] = Query(default=None),
    limit: int = Query(default=message_service.PAGE_SIZE, ge=1, le=message_service.MAX_PAGE_SIZE),
    user: AuthUser = Depends(get_current_user),
):
    try:
        rows = await message_service.list_messages(
            conversation_id, user.id, before=before, limit=limit
        )
    except social.SocialError as exc:
        raise _http_error(exc) from exc
    return {"messages": rows}


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=201,
    dependencies=[Depends(_send_limit)],
)
async def send_message(
    conversation_id: str,
    data: SendMessageRequest,
    user: AuthUser = Depends(get_current_user),
):
    try:
        return await message_service.send(conversation_id, user, data.body)
    except social.SocialError as exc:
        raise _http_error(exc) from exc


@router.post("/conversations/{conversation_id}/read", status_code=204)
async def mark_conversation_read(
    conversation_id: str,
    user: AuthUser = Depends(get_current_user),
):
    try:
        await conversation_service.require_participant(conversation_id, user.id)
        await message_service.mark_read(conversation_id, user.id)
    except social.SocialError as exc:
        raise _http_error(exc) from exc


@router.get("/unread-count")
async def read_unread_count(user: AuthUser = Depends(get_current_user)):
    """
    The nav badge.

    Degrades to zero rather than erroring: a failed poll must not put a toast on
    screen every twenty seconds for a decoration.
    """
    try:
        return {"unread": await conversation_service.unread_total(user.id)}
    except social.SocialError:
        logger.warning("social: unread count unavailable for %s", user.id)
        return {"unread": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCKING
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/blocks")
async def list_blocks(user: AuthUser = Depends(get_current_user)):
    try:
        return {"blocked": await block_service.list_blocked(user.id)}
    except social.SocialError as exc:
        raise _http_error(exc) from exc


@router.post("/blocks/{user_id}", status_code=204)
async def block_member(user_id: str, user: AuthUser = Depends(get_current_user)):
    try:
        await block_service.block(user.id, user_id)
    except social.SocialError as exc:
        raise _http_error(exc) from exc


@router.delete("/blocks/{user_id}", status_code=204)
async def unblock_member(user_id: str, user: AuthUser = Depends(get_current_user)):
    try:
        await block_service.unblock(user.id, user_id)
    except social.SocialError as exc:
        raise _http_error(exc) from exc


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVITY
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/activity")
async def read_activity(user: AuthUser = Depends(get_current_user)):
    """
    The caller's own community numbers.

    Deliberately has no `{user_id}` variant: these are counts about you, shown
    on your own dashboard. Somebody else's public numbers already live on
    `GET /api/profile/public/{user_id}`.
    """
    return await activity_service.get_activity(user.id)
