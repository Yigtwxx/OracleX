"""
Per-user data provider keys.

The same shape as `llm_settings_service`, for the optional market-data upstreams
in `data_provider_presets`. Plaintext leaves this module only through
`get_keys`, which the request dependency uses; everything user-facing goes
through `get_settings`, which returns a last-four hint instead.

One row per (user, provider), so clearing one upstream never disturbs another.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import secret_box
from services.data_provider_presets import DATA_PROVIDERS, USER_PROVIDERS, is_user_provider
from services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

TABLE = "user_data_provider_keys"


class UnknownProvider(ValueError):
    """The requested provider is not a user-configurable data provider."""


def _rows(user_id: str) -> List[Dict[str, Any]]:
    response = get_supabase().table(TABLE).select("*").eq("user_id", user_id).execute()
    return response.data or []


def _by_provider(user_id: str) -> Dict[str, Dict[str, Any]]:
    return {row.get("provider", ""): row for row in _rows(user_id)}


def _public_view(name: str, row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    One provider as the settings panel sees it.

    `source` is the field the panel actually acts on: "user" means this reader's
    own key is in play, "server" means the install's .env is carrying them, and
    "none" is the only state worth prompting about.
    """
    preset = DATA_PROVIDERS[name]
    # Imported here rather than at module scope: provider_keys reads config, and
    # keeping it out of the import graph of a storage module matches the way
    # llm_settings_service avoids importing the client it feeds.
    from services import provider_keys

    user_configured = bool(row and row.get("encrypted_key"))
    server_configured = provider_keys.server_configured(name)

    if user_configured:
        source = "user"
    elif server_configured:
        source = "server"
    else:
        source = "none"

    return {
        "provider": name,
        "label": preset.label,
        "env_var": preset.env_var,
        "scope": preset.scope,
        "benefit": preset.benefit,
        "signup_url": preset.signup_url,
        "placeholder": preset.placeholder,
        "editable": preset.scope == "user",
        "configured": user_configured or server_configured,
        "user_configured": user_configured,
        "server_configured": server_configured,
        "source": source,
        "key_hint": (row or {}).get("key_hint", "") if user_configured else "",
    }


async def get_settings(user_id: str) -> List[Dict[str, Any]]:
    """
    Every provider in the registry, in registry order, credential-free.

    Returns the server-only view on a database failure rather than raising: the
    panel is a settings screen, and showing it with the reader's own keys missing
    beats showing them an error page.
    """
    try:
        stored = _by_provider(user_id)
    except Exception as e:
        logger.error("Could not read data provider keys for user: %s", e)
        stored = {}
    return [_public_view(name, stored.get(name)) for name in DATA_PROVIDERS]


async def get_keys(user_id: str) -> Dict[str, str]:
    """
    The reader's decrypted keys, keyed by provider.

    Providers with no stored key are absent rather than blank, so a caller can
    bind what is present without deciding what a blank means. An undecryptable
    key is dropped with a warning — the secret was rotated, and the reader has to
    re-enter it.
    """
    try:
        stored = _by_provider(user_id)
    except Exception as e:
        logger.error("Could not read data provider credentials for user: %s", e)
        return {}

    keys: Dict[str, str] = {}
    for name in USER_PROVIDERS:
        row = stored.get(name)
        if not row or not row.get("encrypted_key"):
            continue
        try:
            keys[name] = secret_box.decrypt(row["encrypted_key"])
        except secret_box.SecretBoxUnconfigured as e:
            logger.warning("Stored %s key is unusable: %s", name, e)
    return keys


async def save_key(user_id: str, provider: str, api_key: str) -> List[Dict[str, Any]]:
    """
    Store one provider's key for this user.

    A blank `api_key` is rejected rather than treated as a clear: deleting is
    `delete_key`, and silently wiping a working key because a form posted an
    empty box is the failure mode that distinction exists to prevent.
    """
    name = provider.strip().lower()
    if not is_user_provider(name):
        raise UnknownProvider(f"Unknown data provider: {provider}")

    key = api_key.strip()
    if not key:
        raise ValueError("An API key is required. Use delete to remove one.")

    payload = {
        "encrypted_key": secret_box.encrypt(key),
        "key_hint": secret_box.key_hint(key),
        "updated_at": datetime.utcnow().isoformat(),
    }

    table = get_supabase().table(TABLE)
    existing = _by_provider(user_id).get(name)
    if existing:
        table.update(payload).eq("user_id", user_id).eq("provider", name).execute()
    else:
        table.insert({"user_id": user_id, "provider": name, **payload}).execute()

    return await get_settings(user_id)


async def delete_key(user_id: str, provider: str) -> List[Dict[str, Any]]:
    """Remove one provider's key; that upstream falls back to the server's."""
    name = provider.strip().lower()
    if not is_user_provider(name):
        raise UnknownProvider(f"Unknown data provider: {provider}")

    get_supabase().table(TABLE).delete().eq("user_id", user_id).eq("provider", name).execute()
    return await get_settings(user_id)
