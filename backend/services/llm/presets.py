"""
Known LLM providers.

Adding a provider means adding one row here — no new code — as long as it speaks
the OpenAI chat-completions format, which nearly all of them do.

`default_model` is a convenience only: whatever `LLM_PROVIDER`/`LLM_MODEL` says
always wins, and model ids move faster than this file will. If a default has
gone stale the provider answers 404 and `/api/llm/status` lists the ids that
provider actually offers right now.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderPreset:
    """Everything needed to construct a provider except the user's model choice."""

    adapter: str  # "openai_compat" | "anthropic" | "ollama"
    base_url: str
    default_model: str
    key_env: Optional[str]  # None = no credentials needed (local)


PRESETS: dict[str, ProviderPreset] = {
    # ── Local ───────────────────────────────────────────────────────────────
    # base_url is overridden from OLLAMA_BASE_URL at construction time.
    "ollama": ProviderPreset("ollama", "http://localhost:11434", "qwen3.6:35b-a3b", None),
    # ── OpenAI-compatible clouds ────────────────────────────────────────────
    "groq": ProviderPreset(
        "openai_compat", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"
    ),
    # The "-latest" alias is deliberate: Google retires specific Gemini versions
    # (gemini-2.5-flash is already closed to new keys), while the alias keeps
    # tracking whatever the current Flash model is.
    "gemini": ProviderPreset(
        "openai_compat",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-flash-latest",
        "GEMINI_API_KEY",
    ),
    "openai": ProviderPreset(
        "openai_compat", "https://api.openai.com/v1", "gpt-4.1-mini", "OPENAI_API_KEY"
    ),
    "openrouter": ProviderPreset(
        "openai_compat", "https://openrouter.ai/api/v1", "", "OPENROUTER_API_KEY"
    ),
    "deepseek": ProviderPreset(
        "openai_compat", "https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"
    ),
    "together": ProviderPreset(
        "openai_compat", "https://api.together.xyz/v1", "", "TOGETHER_API_KEY"
    ),
    "mistral": ProviderPreset(
        "openai_compat", "https://api.mistral.ai/v1", "mistral-large-latest", "MISTRAL_API_KEY"
    ),
    "xai": ProviderPreset("openai_compat", "https://api.x.ai/v1", "grok-3", "XAI_API_KEY"),
    "cerebras": ProviderPreset(
        "openai_compat", "https://api.cerebras.ai/v1", "llama-3.3-70b", "CEREBRAS_API_KEY"
    ),
    "fireworks": ProviderPreset(
        "openai_compat", "https://api.fireworks.ai/inference/v1", "", "FIREWORKS_API_KEY"
    ),
    "perplexity": ProviderPreset(
        "openai_compat", "https://api.perplexity.ai", "sonar", "PERPLEXITY_API_KEY"
    ),
    # ── Native protocol ─────────────────────────────────────────────────────
    # Anthropic does publish an OpenAI-compatible shim, but its own docs mark it
    # beta and "not intended for production", so we speak /v1/messages directly.
    "anthropic": ProviderPreset(
        "anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-5", "ANTHROPIC_API_KEY"
    ),
    # ── Anything else ───────────────────────────────────────────────────────
    # Self-hosted vLLM, LM Studio, LiteLLM proxy, a provider not listed above:
    # set LLM_BASE_URL (and LLM_API_KEY if it needs one).
    "custom": ProviderPreset("openai_compat", "", "", "LLM_API_KEY"),
}


def preset_names() -> list[str]:
    """All configurable provider names, for error messages and status output."""
    return sorted(PRESETS)


def keyless_provider_names() -> list[str]:
    """
    Providers that authenticate with nothing — the local ones.

    Callers need this to tell "no key supplied" apart from "no key exists". A
    settings form that demands one unconditionally locks a user into whichever
    cloud provider they picked first, because the only way back to Ollama is to
    produce a credential Ollama has never had.
    """
    return sorted(name for name, preset in PRESETS.items() if preset.key_env is None)


def provider_default_models() -> dict[str, str]:
    """
    Each provider's default model id, for a form that offers "blank = default".

    Without it that offer is unreadable: a user is told a default exists but not
    what it is, which is how a Mistral id was left sitting in the field while
    Ollama was selected. Entries are empty for the providers whose model must be
    chosen (openrouter, together, custom), and the docstring above applies —
    these go stale, so they belong in a placeholder, never in a saved value.
    """
    return {name: preset.default_model for name, preset in PRESETS.items()}
