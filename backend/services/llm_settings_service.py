"""
Per-user LLM provider settings.

Stores which provider/model a user chose, their encrypted API key, and which
features that key applies to. The plaintext key leaves this module only through
`get_credentials`, which the provider resolver uses; everything user-facing goes
through `get_settings`, which returns a hint instead.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from services import secret_box
from services.llm.presets import PRESETS, preset_names
from services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

TABLE = "user_llm_settings"

# Feature flags a user can toggle. Background/scheduler work is deliberately
# absent: it has no user context and always uses the server's .env chain.
FEATURES: Tuple[str, ...] = ("chat", "news", "reports")

_TOGGLE_COLUMNS = {feature: f"use_for_{feature}" for feature in FEATURES}


class UnknownProvider(ValueError):
    """The requested provider is not in the preset registry."""


class KeyRequired(ValueError):
    """An API key must be supplied for this change to be valid."""


def _requires_key(provider: str) -> bool:
    """Whether this provider needs a credential. Unknown names are assumed to."""
    preset = PRESETS.get(provider.strip().lower())
    return preset is None or preset.key_env is not None


def _public_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """The shape safe to return to a client — never the key or its ciphertext."""
    return {
        "provider": row.get("provider", ""),
        "model": row.get("model", ""),
        "key_hint": row.get("key_hint", ""),
        "configured": bool(row.get("encrypted_key")),
        "requires_key": _requires_key(row.get("provider", "")),
        "use_for_chat": bool(row.get("use_for_chat", False)),
        "use_for_news": bool(row.get("use_for_news", False)),
        "use_for_reports": bool(row.get("use_for_reports", False)),
    }


def _fetch_row(user_id: str) -> Optional[Dict[str, Any]]:
    response = get_supabase().table(TABLE).select("*").eq("user_id", user_id).execute()
    rows = response.data or []
    return rows[0] if rows else None


async def get_settings(user_id: str) -> Optional[Dict[str, Any]]:
    """The user's settings without any credential material, or None if unset."""
    try:
        row = _fetch_row(user_id)
    except Exception as e:
        logger.error("Could not read LLM settings for user: %s", e)
        return None
    return _public_view(row) if row else None


async def get_credentials(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Settings including the decrypted API key, for building a provider.

    Returns None when there is no row, or when the stored key cannot be
    decrypted with the current secret.
    """
    try:
        row = _fetch_row(user_id)
    except Exception as e:
        logger.error("Could not read LLM credentials for user: %s", e)
        return None
    if not row or not row.get("encrypted_key"):
        return None

    try:
        api_key = secret_box.decrypt(row["encrypted_key"])
    except secret_box.SecretBoxUnconfigured as e:
        logger.warning("Stored LLM key is unusable: %s", e)
        return None

    return {
        "provider": row.get("provider", ""),
        "model": row.get("model", ""),
        "api_key": api_key,
        "use_for_chat": bool(row.get("use_for_chat", False)),
        "use_for_news": bool(row.get("use_for_news", False)),
        "use_for_reports": bool(row.get("use_for_reports", False)),
    }


async def save_settings(
    user_id: str,
    *,
    provider: str,
    model: str = "",
    api_key: Optional[str] = None,
    use_for_chat: Optional[bool] = None,
    use_for_news: Optional[bool] = None,
    use_for_reports: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Create or update a user's LLM settings.

    Omitting `api_key` keeps the stored one, so toggles can be changed without
    re-typing the key. Changing provider requires a key in the same call: the
    stored key belongs to the previous provider and could not work.
    """
    provider = provider.strip().lower()
    if provider not in PRESETS:
        raise UnknownProvider(
            f"Unknown provider '{provider}'. Supported: {', '.join(preset_names())}"
        )

    existing = _fetch_row(user_id)
    provider_changed = bool(existing) and existing.get("provider") != provider

    # Ollama authenticates with nothing, so demanding a key for it is a demand
    # that cannot be met: a user who moved to a cloud provider could never move
    # back through this form. `key_env is None` is the registry's own statement
    # that a provider is keyless, which keeps the rule in one place.
    requires_key = PRESETS[provider].key_env is not None

    if requires_key and not api_key and (existing is None or provider_changed):
        raise KeyRequired("An API key is required for this provider.")

    values: Dict[str, Any] = {
        "user_id": user_id,
        "provider": provider,
        "model": model.strip(),
        "updated_at": datetime.now().isoformat(),
    }

    if api_key:
        values["encrypted_key"] = secret_box.encrypt(api_key)
        values["key_hint"] = secret_box.key_hint(api_key)
    elif provider_changed and not requires_key:
        # The stored key belongs to the provider being left. Keeping it would
        # leave a live credential at rest for an account that no longer uses it,
        # and would report `configured` for a provider that never needed one.
        #
        # Blanked rather than nulled: `encrypted_key` is NOT NULL in the live
        # table, and every reader here tests it for truthiness rather than for
        # None, so an empty string clears it without a schema change.
        values["encrypted_key"] = ""
        values["key_hint"] = ""

    for feature, requested in (
        ("chat", use_for_chat),
        ("news", use_for_news),
        ("reports", use_for_reports),
    ):
        column = _TOGGLE_COLUMNS[feature]
        if requested is not None:
            values[column] = requested
        elif existing is None:
            # A brand-new row defaults to chat only — the least surprising
            # scope for a key a user just handed us.
            values[column] = feature == "chat"

    supabase = get_supabase()
    if existing:
        payload = {k: v for k, v in values.items() if k != "user_id"}
        supabase.table(TABLE).update(payload).eq("user_id", user_id).execute()
    else:
        values["created_at"] = values["updated_at"]
        supabase.table(TABLE).insert(values).execute()

    row = _fetch_row(user_id) or values
    return _public_view(row)


async def delete_settings(user_id: str) -> bool:
    """Remove the user's stored provider and key."""
    try:
        get_supabase().table(TABLE).delete().eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.error("Could not delete LLM settings: %s", e)
        return False
