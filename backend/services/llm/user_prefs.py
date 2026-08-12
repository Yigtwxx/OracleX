"""
Resolve a user's own LLM provider for a given feature.

Returns None whenever the caller is anonymous, has no stored key, or has that
feature switched off — in which case the server's configured chain is used
unchanged.
"""

import logging
from typing import Optional

from services.llm.base import LLMProvider
from services.llm.client import build_provider

logger = logging.getLogger(__name__)


def _storage():
    """
    Import the settings store lazily to break an import cycle.

    `llm_settings_service` imports `services.llm.presets` to validate a provider
    name, which initialises this package — so importing it back at module level
    would leave one of the two half-built. Storage depending on the LLM registry
    is the sane direction; this module is the bridge and absorbs the awkwardness.
    Python caches the module, so this costs one dict lookup per call.
    """
    from services import llm_settings_service

    return llm_settings_service


async def provider_for(user_id: Optional[str], feature: str) -> Optional[LLMProvider]:
    """
    The provider this user wants for `feature`, or None to use the server chain.

    `feature` must be one of llm_settings_service.FEATURES. Anything else — most
    importantly background work, which has no user context — resolves to None.
    """
    storage = _storage()
    if not user_id or feature not in storage.FEATURES:
        return None

    credentials = await storage.get_credentials(user_id)
    if not credentials:
        return None

    if not credentials.get(f"use_for_{feature}"):
        return None

    return build_provider(
        credentials.get("provider", ""),
        credentials.get("model", ""),
        credentials.get("api_key", ""),
    )
