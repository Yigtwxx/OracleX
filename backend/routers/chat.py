"""
Chat Router
Handles Oracle AI chat, chat status, and chat history persistence.
"""

import asyncio
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from dependencies.auth import AuthUser, get_current_user, get_optional_user
from services import analysis_jobs
from services.chat_service import TURN_TIMEOUT, chat_with_oracle, generate_session_title
from services.supabase_service import (
    clear_chat_history,
    create_chat_session,
    delete_chat_session,
    get_chat_history,
    get_session_messages,
    get_user_sessions,
    save_chat_message,
    update_session_title,
)
from utils import Colors, log_header, log_step, log_success, log_info, log_warning

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None
    session_id: Optional[str] = None
    style: Optional[str] = "detailed"  # 'detailed' or 'concise'


class ChatResponse(BaseModel):
    response: str
    thinking_time: float
    # Which context sources actually reached the model, and the asset the
    # question resolved to. Both are computed per turn; surfacing them makes a
    # wrong answer diagnosable without reading the server log.
    sources: List[str] = []
    detected_symbol: Optional[str] = None
    # Set only on the turn that auto-titles a session, so the client can update
    # its sidebar without refetching the session list. None on every other turn.
    session_title: Optional[str] = None


# `user_id` is intentionally absent from these — it comes from the verified
# JWT, never from the client. See dependencies/auth.py.


class ChatStep(BaseModel):
    """One tool step behind an assistant message, as the timeline renders it."""

    id: str
    tool: str
    label: str
    status: str
    detail: Optional[str] = None
    duration_seconds: Optional[float] = None


class SaveChatMessageRequest(BaseModel):
    role: str
    content: str
    session_id: Optional[str] = None
    thinking_time: Optional[float] = None
    steps: Optional[List[ChatStep]] = None


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New Chat"


class UpdateSessionRequest(BaseModel):
    title: str


# ═══════════════════════════════════════════════════════════════════════════════
# ORACLE CHAT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/chat", response_model=ChatResponse)
async def oracle_chat(request: ChatRequest, user: Optional[AuthUser] = Depends(get_optional_user)):
    """
    Chat with Oracle AI assistant.

    Provides intelligent responses about crypto, stocks, and market analysis.
    Uses extended thinking time for quality responses.
    """
    log_header("ORACLE CHAT REQUEST")
    log_step(
        "💬",
        f"Message: {request.message[:100]}..."
        if len(request.message) > 100
        else f"Message: {request.message}",
    )

    # Convert history to dict format
    history = None
    if request.history:
        history = [{"role": m.role, "content": m.content} for m in request.history]
        log_info(f"Conversation history: {len(history)} messages")

    log_step(
        "🤔", "Oracle is thinking (this may take a while for complex questions)...", Colors.PURPLE
    )

    # A session the client just created carries a raw slice of the first message
    # as its title. On that first turn only, replace it with a model-written one.
    # The call is started before the answer and awaited after it, so titling runs
    # inside the answer's latency instead of adding to it. Anonymous turns are
    # skipped: `update_session_title` scopes the write to the owning user.
    title_task: Optional[asyncio.Task] = None
    if user and request.session_id and not history:
        title_task = asyncio.create_task(generate_session_title(request.message, user_id=user.id))

    try:
        result = await chat_with_oracle(
            request.message,
            history,
            style=request.style,
            user_id=user.id if user else None,
        )
    except BaseException:
        if title_task:
            title_task.cancel()
        raise

    session_title = await title_task if title_task else None
    if session_title:
        # Report the title only once it is actually persisted — otherwise the
        # sidebar would show a name the next page load does not have.
        if await update_session_title(request.session_id, session_title, user.id):
            log_info(f"Session auto-titled: {session_title}")
        else:
            log_warning("Session title could not be persisted; leaving the client title in place")
            session_title = None

    log_success(f"Response generated in {result['thinking_time']}s")
    log_info(f"Response length: {len(result['response'])} characters")
    print(f"{Colors.PURPLE}{'═' * 60}{Colors.END}\n")

    return ChatResponse(
        response=result["response"],
        thinking_time=result["thinking_time"],
        sources=result.get("sources", []),
        detected_symbol=result.get("detected_symbol"),
        session_title=session_title,
    )


@router.post("/api/chat/jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_chat_job(
    request: ChatRequest, user: Optional[AuthUser] = Depends(get_optional_user)
):
    """
    Start a turn as a background job the client polls.

    Same pipeline as `POST /api/chat`; the difference is that the steps are
    reported while they run instead of the connection being held open until an
    answer exists.
    """
    log_header("ORACLE CHAT JOB")
    log_step("💬", f"Message: {request.message[:100]}")

    history = None
    if request.history:
        history = [{"role": m.role, "content": m.content} for m in request.history]

    user_id = user.id if user else None
    session_id = request.session_id
    should_title = bool(user and session_id and not history)

    async def runner(controls) -> dict:
        # Titling starts alongside the turn and is collected after it, so it
        # runs inside the answer's latency rather than adding to it.
        title_task: Optional[asyncio.Task] = None
        if should_title:
            title_task = asyncio.create_task(
                generate_session_title(request.message, user_id=user_id)
            )

        try:
            result = await asyncio.wait_for(
                chat_with_oracle(
                    request.message,
                    history,
                    style=request.style,
                    user_id=user_id,
                    on_step=controls.on_step,
                ),
                timeout=TURN_TIMEOUT,
            )
        except BaseException:
            if title_task:
                title_task.cancel()
            raise

        session_title = await title_task if title_task else None
        if session_title and not await update_session_title(session_id, session_title, user_id):
            log_warning("Session title could not be persisted; leaving the client title in place")
            session_title = None

        return {**result, "session_title": session_title}

    # A fresh key per request: `analysis_jobs.start` dedups on (kind, key)
    # because two callers wanting the daily report want the same artifact, but
    # two chat turns never are. Keying on the session would silently merge a
    # double-tap into one answer and drop a message.
    job = await analysis_jobs.start(
        uuid.uuid4().hex, analysis_jobs.KIND_CHAT, [], runner, owner_id=user_id
    )
    return job.to_dict()


@router.get("/api/chat/jobs/{job_id}")
async def get_chat_job(job_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    """
    Poll a chat job.

    404 rather than 403 on someone else's job: a chat job holds a question and
    its answer, and confirming that an id exists is already more than a stranger
    should learn.
    """
    job = await analysis_jobs.get_job(job_id)
    user_id = user.id if user else None
    if job is None or job.kind != analysis_jobs.KIND_CHAT or job.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Chat job not found")
    return job.to_dict()


@router.get("/api/chat/status")
async def chat_status():
    """Check if Oracle chat is available, and which provider is serving it."""
    from services import llm

    info = await llm.active_provider_info()
    active = info.get("active")
    return {
        "available": active is not None,
        "provider": active["provider"] if active else None,
        "model": active["model"] if active else None,
        "message": (
            f"Oracle is ready ({active['provider']})"
            if active
            else "None of the configured AI providers are responding"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT SESSION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/chat/sessions")
async def get_user_sessions_endpoint(user: AuthUser = Depends(get_current_user)):
    """Get all chat sessions for the authenticated user."""
    sessions = await get_user_sessions(user.id)
    return {"sessions": sessions}


@router.post("/api/chat/sessions")
async def create_session_endpoint(
    request: CreateSessionRequest, user: AuthUser = Depends(get_current_user)
):
    """Create a new chat session owned by the authenticated user."""
    return await create_chat_session(user.id, request.title)


@router.put("/api/chat/sessions/{session_id}")
async def update_session_endpoint(
    session_id: str,
    request: UpdateSessionRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Rename a chat session. Scoped to the authenticated user's sessions."""
    success = await update_session_title(session_id, request.title, user.id)
    return {"success": success}


@router.delete("/api/chat/sessions/{session_id}")
async def delete_session_endpoint(session_id: str, user: AuthUser = Depends(get_current_user)):
    """Delete a chat session. Scoped to the authenticated user's sessions."""
    success = await delete_chat_session(session_id, user.id)
    return {"success": success}


@router.get("/api/chat/sessions/{session_id}/messages")
async def get_session_messages_endpoint(
    session_id: str, user: AuthUser = Depends(get_current_user)
):
    """Get messages for a session owned by the authenticated user."""
    messages = await get_session_messages(session_id, user.id)
    return {"messages": messages}


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT HISTORY ENDPOINTS (Legacy / Direct Message)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/chat/history")
async def get_chat_history_endpoint(limit: int = 50, user: AuthUser = Depends(get_current_user)):
    """
    Get chat history for the authenticated user.
    Automatically cleans up messages older than 7 days.
    """
    messages = await get_chat_history(user.id, limit)
    return {"messages": messages, "count": len(messages)}


@router.post("/api/chat/history")
async def save_chat_message_endpoint(
    request: SaveChatMessageRequest, user: AuthUser = Depends(get_current_user)
):
    """Save a chat message attributed to the authenticated user."""
    result = await save_chat_message(
        user_id=user.id,
        role=request.role,
        content=request.content,
        session_id=request.session_id,
        thinking_time=request.thinking_time,
        steps=[s.model_dump() for s in request.steps] if request.steps else None,
    )
    return {"success": True, "message": result}


@router.delete("/api/chat/history")
async def clear_chat_history_endpoint(user: AuthUser = Depends(get_current_user)):
    """Clear all chat history for the authenticated user."""
    success = await clear_chat_history(user.id)
    return {"success": success}
