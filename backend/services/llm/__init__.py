"""
Multi-provider LLM layer.

The provider is chosen in .env (`LLM_PROVIDER`), with an optional fallback chain
(`LLM_FALLBACK_PROVIDERS`). Local Ollama and roughly a dozen cloud providers are
supported; see `presets.py`.

    from services import llm

    text = await llm.generate("Summarise this", system="Be brief", reasoning=False)
"""

from services.llm.base import (
    GenerationRequest,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)
from services.llm.client import (
    active_provider_info,
    build_provider,
    clear_cooldowns,
    cooldown_remaining,
    generate,
    get_chain,
    llm_health,
)
from services.llm.presets import (
    PRESETS,
    keyless_provider_names,
    preset_names,
    provider_default_models,
)
from services.llm.user_prefs import provider_for

__all__ = [
    "generate",
    "llm_health",
    "active_provider_info",
    "get_chain",
    "build_provider",
    "provider_for",
    "keyless_provider_names",
    "preset_names",
    "provider_default_models",
    "cooldown_remaining",
    "clear_cooldowns",
    "PRESETS",
    "GenerationRequest",
    "LLMProvider",
    "LLMError",
    "LLMRateLimitError",
    "LLMRequestError",
    "LLMTransientError",
    "LLMUnavailableError",
]
