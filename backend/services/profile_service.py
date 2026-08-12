"""Profile service for user management, subscriptions, and settings."""

import asyncio
import logging
from datetime import datetime, date
from typing import Dict, Optional, Any

from services import storage
from services.supabase_service import get_supabase


logger = logging.getLogger(__name__)

# Buckets that hold objects keyed by user id. Storage is the one thing account
# deletion has to clean up by hand — see `delete_account`.
_USER_BUCKETS = ("profile-avatars", "community-media")


class ProfileError(Exception):
    """The profile store could not answer, or the write did not happen."""


class ProfileStoreError(ProfileError):
    """
    A write was refused by the database.

    Distinct from "no row matched", which is an ordinary `False`. A subclass so
    the two routes already catching `ProfileError` keep catching this too.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def get_user_profile(user_id: str, email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get user profile with subscription info.
    Creates a default profile if one doesn't exist.

    `email` is written onto a profile this function has to create. Rows created
    by the `handle_new_user()` trigger already carry it; rows created here used
    to be left with a NULL email, which is exactly the column the admin list and
    the sign-up duplicate check read.

    Raises `ProfileError` when the database cannot answer. It used to swallow
    the exception and return a fabricated free-plan profile, which told a paying
    subscriber they were on Free every time Supabase hiccuped.
    """
    try:
        supabase = get_supabase()

        # First try to get existing profile
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        raise ProfileError(str(e)) from e

    if response.data and len(response.data) > 0:
        profile = response.data[0]

        # Reset AI queries if new day
        if profile.get("ai_queries_reset_at"):
            reset_date = profile["ai_queries_reset_at"]
            if isinstance(reset_date, str):
                reset_date = date.fromisoformat(reset_date.split("T")[0])

            if reset_date < date.today():
                # Reset queries for new day. Best effort: this is a side effect
                # of reading the profile, not the point of the call, so a
                # refused write must not turn a readable profile into an error.
                # The counter still reads as 0 for this response and the reset
                # is retried on the next read.
                try:
                    await update_user_profile(
                        user_id,
                        {"ai_queries_today": 0, "ai_queries_reset_at": date.today().isoformat()},
                    )
                except ProfileStoreError:
                    logger.warning("profile: daily query reset failed for %s", user_id)
                profile["ai_queries_today"] = 0

        # Add computed fields
        plan = profile.get("subscription_plan", "free")
        profile["ai_query_limit"] = 5 if plan == "free" else 999999
        profile["ai_queries_remaining"] = max(
            0, profile["ai_query_limit"] - profile.get("ai_queries_today", 0)
        )

        return profile

    # Profile doesn't exist - create a default one
    logger.info(f"Creating default profile for user: {user_id}")
    default_profile = {
        "id": user_id,
        "email": email,
        "subscription_plan": "free",
        "ai_queries_today": 0,
        "ai_queries_reset_at": date.today().isoformat(),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    try:
        # Use upsert to handle race conditions or existing profiles safely
        supabase.table("profiles").upsert(default_profile).execute()
    except Exception as insert_error:
        logger.error(f"Could not create profile for {user_id}: {insert_error}")
        raise ProfileError(str(insert_error)) from insert_error

    # Return default profile with computed fields
    default_profile["ai_query_limit"] = 5
    default_profile["ai_queries_remaining"] = 5
    return default_profile


async def update_user_profile(user_id: str, data: Dict[str, Any]) -> bool:
    """
    Update user profile fields.
    Allowed fields: full_name, avatar_url, bio, subscription_plan, ai_queries_today,
    ai_queries_reset_at

    Returns False when the update matched no row — the profile is not there.
    Raises `ProfileStoreError` when the database refused the write.

    Those two used to be the same `False`, and the router turns False into 404
    "Profile not found". Saving a bio before `profiles.bio` existed therefore
    answered "Profile not found" about a profile that was sitting right there,
    which sent the reader looking in exactly the wrong place. A write that fails
    has to say so.

    The False case itself is also load-bearing: this once tested
    `response.data is not None`, and PostgREST answers an update that matched
    nothing with `[]`, which is not None — so every write to a missing profile
    reported success.
    """
    allowed_fields = [
        "full_name",
        "avatar_url",
        "bio",
        "subscription_plan",
        "subscription_expires_at",
        "ai_queries_today",
        "ai_queries_reset_at",
    ]

    filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
    filtered_data["updated_at"] = datetime.now().isoformat()

    try:
        supabase = get_supabase()

        response = supabase.table("profiles").update(filtered_data).eq("id", user_id).execute()
    except Exception as e:
        # The column names are ours, not user content, so they are safe to log
        # and they are the whole diagnostic — a missing column reads as
        # PGRST204 here and as nothing at all further up.
        logger.error("profile: update of %s failed: %s", sorted(filtered_data), e)
        raise ProfileStoreError(str(e)) from e

    return bool(response.data)


async def delete_account(user_id: str) -> None:
    """
    Erase the account and everything hanging off it.

    Order matters. Storage first, because it is the only part Postgres will not
    do for us: every table this app owns reaches `auth.users` through a chain of
    `ON DELETE CASCADE` foreign keys, so removing the auth row takes `profiles`,
    `watchlists`, `notes`, `alerts`, `chat_sessions`, `chat_messages`,
    `connected_accounts`, `user_settings`, `user_llm_settings` and — transitively
    through `profiles` — every community post, comment and vote with it. Audit
    log entries survive with a NULL `actor_id` on purpose, so a moderation record
    outlives the account it describes.

    Storage failures are logged and do not abort the deletion. Orphaned bytes in
    a bucket are a smaller problem than an account that is half deleted.
    """
    for bucket in _USER_BUCKETS:
        try:
            paths = await storage.list_user_objects(bucket=bucket, user_id=user_id)
            await storage.remove_objects(bucket=bucket, paths=paths)
        except Exception as e:
            logger.warning("profile: could not clear %s for %s: %s", bucket, user_id, e)

    try:
        await asyncio.to_thread(lambda: get_supabase().auth.admin.delete_user(user_id))
    except Exception as e:
        logger.error(f"Error deleting account {user_id}: {e}")
        raise ProfileError(str(e)) from e

    logger.info("profile: deleted account %s", user_id)


async def increment_ai_queries(user_id: str) -> Dict[str, Any]:
    """
    Increment AI query count for user. Returns updated count and limit info.
    """
    profile = await get_user_profile(user_id)

    if not profile:
        return {"allowed": False, "reason": "Profile not found"}

    current_count = profile.get("ai_queries_today", 0)
    limit = profile.get("ai_query_limit", 5)

    if current_count >= limit:
        return {
            "allowed": False,
            "reason": "Daily AI query limit reached",
            "queries_today": current_count,
            "limit": limit,
            "plan": profile.get("subscription_plan", "free"),
        }

    # Increment count. Not best-effort, unlike the resets above: this write *is*
    # the quota. If it does not land, granting the query anyway would hand out
    # an unlimited allowance for as long as the failure lasts, so this fails
    # closed and says why.
    try:
        await update_user_profile(user_id, {"ai_queries_today": current_count + 1})
    except ProfileStoreError:
        logger.error("profile: could not record an AI query for %s", user_id)
        return {
            "allowed": False,
            "reason": "Your usage could not be recorded. Try again in a moment.",
            "queries_today": current_count,
            "limit": limit,
            "plan": profile.get("subscription_plan", "free"),
        }

    return {
        "allowed": True,
        "queries_today": current_count + 1,
        "limit": limit,
        "remaining": limit - current_count - 1,
        "plan": profile.get("subscription_plan", "free"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def get_subscription(user_id: str) -> Dict[str, Any]:
    """
    Get user's current subscription info.
    """
    profile = await get_user_profile(user_id)

    if not profile:
        return {"plan": "free", "expires_at": None, "features": get_plan_features("free")}

    plan = profile.get("subscription_plan", "free")
    expires_at = profile.get("subscription_expires_at")

    # Check if subscription expired
    if expires_at and plan != "free":
        exp_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if exp_date < datetime.now(exp_date.tzinfo):
            # Subscription expired, downgrade to free. Best effort for the same
            # reason the counter reset above is: the caller asked what the plan
            # is, and the answer — "free", because it has expired — is correct
            # whether or not the row has caught up yet.
            try:
                await update_user_profile(user_id, {"subscription_plan": "free"})
            except ProfileStoreError:
                logger.warning("profile: expiry downgrade failed for %s", user_id)
            plan = "free"

    return {
        "plan": plan,
        "expires_at": expires_at,
        "features": get_plan_features(plan),
        "ai_queries_today": profile.get("ai_queries_today", 0),
        "ai_query_limit": profile.get("ai_query_limit", 5),
    }


async def update_subscription(user_id: str, plan: str, duration_days: int = 30) -> bool:
    """
    Update user's subscription plan.
    For production, this would integrate with Stripe/payment processor.
    """
    if plan not in ["free", "pro", "whale"]:
        return False

    expires_at = None
    if plan != "free":
        from datetime import timedelta

        expires_at = (datetime.now() + timedelta(days=duration_days)).isoformat()

    return await update_user_profile(
        user_id, {"subscription_plan": plan, "subscription_expires_at": expires_at}
    )


def get_plan_features(plan: str) -> Dict[str, Any]:
    """
    Get features available for a subscription plan.
    """
    plans = {
        "free": {
            "name": "Free",
            "price": 0,
            "news_delay_minutes": 15,
            "ai_queries_per_day": 5,
            "live_liquidation": False,
            "advanced_alerts": False,
            "api_access": False,
            "priority_support": False,
        },
        "pro": {
            "name": "Pro",
            "price": 29,
            "news_delay_minutes": 0,
            "ai_queries_per_day": 999999,
            "live_liquidation": True,
            "advanced_alerts": True,
            "api_access": False,
            "priority_support": False,
        },
        "whale": {
            "name": "Whale",
            "price": 99,
            "news_delay_minutes": 0,
            "ai_queries_per_day": 999999,
            "live_liquidation": True,
            "advanced_alerts": True,
            "api_access": True,
            "priority_support": True,
        },
    }

    return plans.get(plan, plans["free"])


# ═══════════════════════════════════════════════════════════════════════════════
# USER SETTINGS FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def get_user_settings(user_id: str) -> Dict[str, Any]:
    """
    Get user settings, create defaults if not exists.

    `.limit(1)` rather than `.single()`: PostgREST answers `.single()` on zero
    rows with an error, so the "create defaults" branch below was unreachable —
    every settings read for a new user landed in the exception handler and got
    an in-memory default that was never stored.
    """
    try:
        supabase = get_supabase()

        response = (
            supabase.table("user_settings").select("*").eq("user_id", user_id).limit(1).execute()
        )

        if response.data:
            return response.data[0]

        # Create default settings
        default_settings = {
            "user_id": user_id,
            "theme": "dark",
            "notifications_enabled": True,
            "email_alerts": False,
            "telegram_alerts": False,
            "default_market": "crypto",
            "dm_enabled": True,
        }

        supabase.table("user_settings").insert(default_settings).execute()
        return default_settings

    except Exception as e:
        logger.error(f"Error getting settings: {e}")

    return {
        "theme": "dark",
        "notifications_enabled": True,
        "email_alerts": False,
        "telegram_alerts": False,
        "default_market": "crypto",
        "dm_enabled": True,
    }


async def update_user_settings(user_id: str, settings: Dict[str, Any]) -> bool:
    """
    Update user settings.
    """
    allowed_fields = [
        "theme",
        "notifications_enabled",
        "email_alerts",
        "telegram_alerts",
        "default_market",
        # Whether other members may open a conversation with this account.
        # Anything missing from this list is dropped silently — the endpoint
        # still reports success — so a new settings column that is not added
        # here looks like it saved and did not. See test_social_dm.py.
        "dm_enabled",
    ]

    filtered_settings = {k: v for k, v in settings.items() if k in allowed_fields}
    filtered_settings["updated_at"] = datetime.now().isoformat()

    try:
        supabase = get_supabase()

        # Check if settings exist
        existing = supabase.table("user_settings").select("id").eq("user_id", user_id).execute()

        if existing.data:
            supabase.table("user_settings").update(filtered_settings).eq(
                "user_id", user_id
            ).execute()
        else:
            filtered_settings["user_id"] = user_id
            supabase.table("user_settings").insert(filtered_settings).execute()

        return True
    except Exception as e:
        logger.error(f"Error updating settings: {e}")

    return False
