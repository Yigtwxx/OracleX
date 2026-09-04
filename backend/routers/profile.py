"""
Profile Router
Handles user profiles, subscriptions, social links, settings, and AI query tracking.

Every route here is scoped to the *authenticated* caller. The user id is taken
from the verified JWT via `get_current_user` and never from the request — see
`dependencies/auth.py` for why that matters given the service-role key.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from dependencies.auth import AuthUser, get_current_user, require_admin
from services import (
    llm,
    llm_settings_service,
    profile_service,
    secret_box,
    social_links_service,
    storage,
)
from services.admin import users as admin_users
from services.admin.audit import AuditActor
from services.admin.errors import AdminError

logger = logging.getLogger(__name__)

router = APIRouter()

# The bucket created by `011_profile_auth.sql`. Separate from `community-media`
# so that clearing a deleted user's avatars cannot touch their post images, and
# so the object's location says what it is.
AVATAR_BUCKET = "profile-avatars"

# Deliberately smaller than the 5 MB post-image budget: this renders at 40px.
AVATAR_MAX_BYTES = 2 * 1024 * 1024

_PROFILE_UNAVAILABLE = HTTPException(
    status_code=503, detail="Your profile is unavailable right now."
)


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class ProfileUpdate(BaseModel):
    """
    User-editable profile fields.

    Deliberately excludes `subscription_plan` / `subscription_expires_at`:
    `profile_service.update_user_profile` allows them, so accepting a free-form
    dict here would let any caller grant themselves a paid plan. Subscription
    changes go through the dedicated endpoint below.
    """

    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    plan: str = "free"
    duration_days: int = 30


class SocialLinkInput(BaseModel):
    """
    One self-declared link.

    `url` is only read when `platform == "custom"`. For every known platform the
    server builds the URL from its own template, so a caller cannot point an
    `x` entry at somewhere that is not X.
    """

    platform: str
    handle: Optional[str] = None
    label: Optional[str] = None
    url: Optional[str] = None


class SocialLinksUpdate(BaseModel):
    """The caller's whole link set. There are no per-link endpoints."""

    links: list[SocialLinkInput] = []


class DeleteAccountRequest(BaseModel):
    """Confirmation for an irreversible delete: the caller's own address."""

    confirm_email: str = ""


class SettingsUpdate(BaseModel):
    theme: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    email_alerts: Optional[bool] = None
    telegram_alerts: Optional[bool] = None
    default_market: Optional[str] = None
    # The "accept direct messages" switch. Also needs adding to the allowlist in
    # profile_service.update_user_settings — a field accepted here but missing
    # there is dropped silently and still answers 200.
    dm_enabled: Optional[bool] = None


class LLMSettingsUpdate(BaseModel):
    """
    A user's AI provider choice.

    `api_key` is optional so the feature toggles can be changed without
    re-typing the key; the service rejects the combination of a new provider
    and no key.
    """

    provider: str
    model: str = ""
    api_key: Optional[str] = None
    use_for_chat: Optional[bool] = None
    use_for_news: Optional[bool] = None
    use_for_reports: Optional[bool] = None
    use_for_notes: Optional[bool] = None


class LLMTestRequest(BaseModel):
    """
    A candidate provider/key to validate before storing it.

    `api_key` defaults to empty because the local providers have none, and a
    user moving back to Ollama still deserves to confirm the daemon answers
    before saving.
    """

    provider: str
    model: str = ""
    api_key: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/profile")
async def get_user_profile(user: AuthUser = Depends(get_current_user)):
    """Get the authenticated user's profile with subscription info."""
    try:
        # The address comes from the verified token, and is only used if this
        # call has to create the row — profiles the signup trigger made already
        # carry it.
        profile = await profile_service.get_user_profile(user.id, email=user.email)
    except profile_service.ProfileError:
        raise _PROFILE_UNAVAILABLE
    if profile:
        try:
            profile["social_links"] = await social_links_service.get_links(user.id)
        except social_links_service.LinkStoreError:
            # The profile is still worth showing without them.
            profile["social_links"] = []
        return profile
    raise HTTPException(status_code=404, detail="Profile not found")


@router.put("/api/profile")
async def update_user_profile(data: ProfileUpdate, user: AuthUser = Depends(get_current_user)):
    """Update the authenticated user's profile."""
    # exclude_unset so omitted fields aren't written back as NULL.
    try:
        success = await profile_service.update_user_profile(
            user.id, data.model_dump(exclude_unset=True)
        )
    except profile_service.ProfileStoreError:
        # The database refused the write. Reporting that as 404 would blame the
        # profile — which is right there — and send whoever is debugging it
        # looking for a missing row instead of at the server log, where the
        # actual refusal is named.
        raise _PROFILE_UNAVAILABLE
    if success:
        return {"success": True}
    # Nothing matched. A profile that isn't there is a 404, not a bad request —
    # the body was fine.
    raise HTTPException(status_code=404, detail="Profile not found")


@router.get("/api/profile/subscription")
async def get_subscription(user: AuthUser = Depends(get_current_user)):
    """Get the authenticated user's current subscription info."""
    return await profile_service.get_subscription(user.id)


@router.post("/api/profile/subscription")
async def update_subscription(data: SubscriptionUpdate, actor: AuthUser = Depends(require_admin)):
    """
    Set the caller's own subscription plan. Admin only.

    This route used to take `get_current_user`, which meant any signed-in caller
    could grant themselves `whale` with one curl. Nothing in the frontend has
    ever called it — the upgrade buttons on the profile page have no click
    handler — so locking it down breaks no client.

    It is now a strictly narrower duplicate of
    `POST /api/admin/users/{user_id}/plan`, which can target any account and
    writes an audit entry. Kept as a 403 rather than deleted so an old client
    gets an honest answer; it should go in a follow-up.
    """
    try:
        user = await admin_users.set_plan(
            user_id=actor.id,
            plan=data.plan,
            duration_days=data.duration_days,
            actor=AuditActor(id=actor.id, email=actor.email),
        )
    except AdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "plan": user.subscription_plan}


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL LINKS
# ═══════════════════════════════════════════════════════════════════════════════
#
# What stood here was an OAuth surface that never worked: `POST
# /api/profile/accounts/{provider}` took an `access_token` from the request body
# and stored it, for providers no application had ever been registered with. No
# client called it. Self-declared links do what the profile page actually needed.


@router.put("/api/profile/social-links")
async def replace_social_links(data: SocialLinksUpdate, user: AuthUser = Depends(get_current_user)):
    """
    Replace the authenticated caller's social links.

    A full replace rather than per-link routes: the set is small, the editor
    saves it as a whole, and a partial update would need an id the client has
    no other use for.
    """
    try:
        links = await social_links_service.replace_links(
            user.id, [item.model_dump() for item in data.links]
        )
    except social_links_service.InvalidLink as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except social_links_service.LinkStoreError:
        raise HTTPException(status_code=502, detail="Your links could not be saved right now.")

    return {"links": links}


@router.get("/api/profile/public/{user_id}")
async def get_public_profile(user_id: str, user: AuthUser = Depends(get_current_user)):
    """
    Another user's profile, as this signed-in caller may see it.

    `get_current_user` is the access rule, not decoration: these pages are for
    members, and a logged-out fetch would put every member's name and bio within
    reach of anything that can make an HTTP request.

    The handles here are self-declared. Nothing has verified that they belong to
    this person, and no response field should suggest otherwise.
    """
    try:
        profile = await social_links_service.get_public_profile(user_id)
    except social_links_service.LinkStoreError:
        raise _PROFILE_UNAVAILABLE

    if profile is None:
        raise HTTPException(status_code=404, detail="No such profile.")

    return profile


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE PHOTO
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/profile/avatar")
async def upload_avatar(file: UploadFile = File(...), user: AuthUser = Depends(get_current_user)):
    """
    Replace the authenticated user's profile photo.

    The body is read with a hard ceiling rather than trusting `content-length`,
    which the client controls, and the file type is decided by its magic bytes
    rather than its name — a PHP script called `me.png` is refused here.

    The previous photo is deleted afterwards. Pruning the whole per-user folder
    is what saves a second column on `profiles` to track the object path.
    """
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Images must be 2 MB or smaller")

    try:
        url, path = await storage.upload_image(
            bucket=AVATAR_BUCKET,
            user_id=user.id,
            data=data,
            max_bytes=AVATAR_MAX_BYTES,
            declared_name=file.filename,
        )
    except storage.ImageRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except storage.StorageFailure:
        raise HTTPException(status_code=502, detail="The image store is unavailable right now.")

    await _prune_avatars(user.id, keep=path)

    try:
        written = await profile_service.update_user_profile(user.id, {"avatar_url": url})
    except profile_service.ProfileStoreError:
        # The bytes are in the bucket but the row does not point at them. Say
        # so rather than 404 — the upload half succeeded and a retry is right.
        raise _PROFILE_UNAVAILABLE
    if not written:
        raise HTTPException(status_code=404, detail="Profile not found")

    return {"url": url, "path": path}


@router.delete("/api/profile/avatar")
async def delete_avatar(user: AuthUser = Depends(get_current_user)):
    """Remove the authenticated user's profile photo and fall back to initials."""
    await _prune_avatars(user.id, keep=None)
    try:
        await profile_service.update_user_profile(user.id, {"avatar_url": None})
    except profile_service.ProfileStoreError:
        raise _PROFILE_UNAVAILABLE
    return {"success": True}


async def _prune_avatars(user_id: str, *, keep: Optional[str]) -> None:
    """
    Delete every object in the user's avatar folder except `keep`.

    Best-effort: a bucket that will not list or delete is worth a log line, not
    a failed upload — the new photo is already stored and already referenced.
    """
    try:
        paths = await storage.list_user_objects(bucket=AVATAR_BUCKET, user_id=user_id)
        stale = [p for p in paths if p != keep]
        await storage.remove_objects(bucket=AVATAR_BUCKET, paths=stale)
    except storage.StorageError as exc:
        logger.warning("profile: could not prune old avatars for %s: %s", user_id, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT DELETION
# ═══════════════════════════════════════════════════════════════════════════════


@router.delete("/api/profile/account", status_code=204)
async def delete_account(data: DeleteAccountRequest, user: AuthUser = Depends(get_current_user)):
    """
    Erase the authenticated user's account. Irreversible.

    The caller has to echo their own address. A `DELETE` that needs no body is
    one stray fetch away from destroying an account, and this is the server-side
    half of the confirmation dialog — a client that skips the dialog still has
    to prove the request was deliberate.
    """
    typed = (data.confirm_email or "").strip().lower()
    if not user.email or typed != user.email.strip().lower():
        raise HTTPException(status_code=400, detail="The address does not match this account.")

    try:
        await profile_service.delete_account(user.id)
    except profile_service.ProfileError:
        raise HTTPException(status_code=502, detail="The account could not be deleted right now.")

    return Response(status_code=204)


@router.get("/api/profile/settings")
async def get_user_settings(user: AuthUser = Depends(get_current_user)):
    """Get the authenticated user's settings."""
    return await profile_service.get_user_settings(user.id)


@router.put("/api/profile/settings")
async def update_user_settings(data: SettingsUpdate, user: AuthUser = Depends(get_current_user)):
    """Update the authenticated user's settings."""
    success = await profile_service.update_user_settings(
        user.id, data.model_dump(exclude_unset=True)
    )
    if success:
        return {"success": True}
    raise HTTPException(status_code=400, detail="Failed to update settings")


@router.post("/api/profile/ai-query")
async def increment_ai_query(user: AuthUser = Depends(get_current_user)):
    """Increment the authenticated user's AI query count and check limits."""
    return await profile_service.increment_ai_queries(user.id)


# ═══════════════════════════════════════════════════════════════════════════════
# PER-USER LLM PROVIDER
#
# The API key is write-only across this whole section: it is accepted, encrypted
# and stored, but no response ever contains it — only the last-four hint.
# ═══════════════════════════════════════════════════════════════════════════════

_NOT_CONFIGURED = HTTPException(
    status_code=503,
    detail=("Per-user API keys are disabled: LLM_KEY_ENCRYPTION_SECRET is not set on the server."),
)

_EMPTY_LLM_SETTINGS = {
    "provider": "",
    "model": "",
    "key_hint": "",
    "configured": False,
    "requires_key": True,
    "use_for_chat": False,
    "use_for_news": False,
    "use_for_reports": False,
    "use_for_notes": False,
}


@router.get("/api/profile/llm")
async def get_llm_settings(user: AuthUser = Depends(get_current_user)):
    """The caller's AI provider settings. Never includes the API key."""
    settings = await llm_settings_service.get_settings(user.id)
    return {
        **(settings or _EMPTY_LLM_SETTINGS),
        "encryption_available": secret_box.is_configured(),
        "supported_providers": llm.preset_names(),
        # So the form can drop the key requirement for the provider the user is
        # about to pick, not just the one already stored.
        "keyless_providers": llm.keyless_provider_names(),
        # Shown as the model field's placeholder, so "blank = default" says what
        # the default actually is.
        "provider_defaults": llm.provider_default_models(),
    }


@router.put("/api/profile/llm")
async def update_llm_settings(data: LLMSettingsUpdate, user: AuthUser = Depends(get_current_user)):
    """Store the caller's provider choice and (optionally) a new API key."""
    # Encryption is only in the way when there is something to encrypt. Refusing
    # a keyless provider here would contradict the settings service, which lets
    # one be saved without a key, and would strand a user on an unset
    # LLM_KEY_ENCRYPTION_SECRET with no way to select their local daemon.
    if data.api_key and not secret_box.is_configured():
        raise _NOT_CONFIGURED

    try:
        return await llm_settings_service.save_settings(
            user.id,
            provider=data.provider,
            model=data.model,
            api_key=data.api_key,
            use_for_chat=data.use_for_chat,
            use_for_news=data.use_for_news,
            use_for_reports=data.use_for_reports,
            use_for_notes=data.use_for_notes,
        )
    except (llm_settings_service.UnknownProvider, llm_settings_service.KeyRequired) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/api/profile/llm")
async def delete_llm_settings(user: AuthUser = Depends(get_current_user)):
    """Remove the caller's provider and key; AI falls back to the server chain."""
    if await llm_settings_service.delete_settings(user.id):
        return {"success": True}
    raise HTTPException(status_code=400, detail="Failed to delete AI provider settings")


@router.post("/api/profile/llm/test")
async def test_llm_settings(data: LLMTestRequest, user: AuthUser = Depends(get_current_user)):
    """
    Check a provider/key pair without storing it.

    Exists so a user cannot save a broken key, silently fall back to the server
    chain, and believe their own key is working.
    """
    provider = llm.build_provider(data.provider, data.model, data.api_key)
    if provider is None:
        return {"ok": False, "error": "Unknown provider, or no model given for it."}

    if not await provider.health():
        return {
            "ok": False,
            "error": "The provider rejected this key or is unreachable.",
            "models": [],
        }

    return {"ok": True, "provider": provider.name, "models": await provider.list_models()}
