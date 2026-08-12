"""
The LLM entry point every AI feature calls.

Resolves the configured provider chain, retries transient faults against the
current provider, and falls through to the next provider when one is genuinely
unusable.
"""

import logging
import re
import time
from typing import Any, Optional

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from services.llm.base import (
    GenerationRequest,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)
from services.llm.presets import PRESETS, preset_names
from services.llm.providers import ADAPTERS
from services.health_registry import health

logger = logging.getLogger(__name__)

# Reasoning models leak their scratchpad into the body as <think>…</think>.
# Stripped centrally so every caller sees clean prose regardless of provider.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _parse_spec(spec: str) -> tuple[str, str]:
    """
    Split a "provider:model" entry.

    Only the first colon separates the two, so Ollama tags survive intact:
    "ollama:qwen3.6:35b-a3b" -> ("ollama", "qwen3.6:35b-a3b").
    """
    name, _, model = spec.strip().partition(":")
    return name.strip().lower(), model.strip()


def build_provider(name: str, model: str = "", api_key: str = "") -> Optional[LLMProvider]:
    """
    Construct a provider from explicit values.

    Used for per-user keys and for validating a key before it is stored, where
    the values come from the request rather than from settings.
    """
    name = name.strip().lower()
    preset = PRESETS.get(name)
    if preset is None:
        logger.error("Unknown LLM provider '%s'. Available: %s", name, ", ".join(preset_names()))
        return None

    resolved_model = model.strip() or preset.default_model
    if not resolved_model:
        logger.error("Provider '%s' has no default model — a model must be given.", name)
        return None

    base_url = preset.base_url
    if name == "ollama":
        base_url = settings.OLLAMA_BASE_URL
    elif not base_url:
        base_url = settings.LLM_BASE_URL
        if not base_url:
            logger.error("Provider '%s' needs LLM_BASE_URL to be set.", name)
            return None

    return ADAPTERS[preset.adapter](
        name=name, base_url=base_url, model=resolved_model, api_key=api_key
    )


def _build_provider(spec: str) -> Optional[LLMProvider]:
    """Construct one provider from a chain entry, or None if unconfigurable."""
    name, model = _parse_spec(spec)
    if not name:
        return None

    preset = PRESETS.get(name)
    if preset is None:
        logger.error("Unknown LLM provider '%s'. Available: %s", name, ", ".join(preset_names()))
        return None

    # An explicit "provider:model" always wins. Otherwise LLM_MODEL only applies
    # to Ollama — it holds an Ollama tag on existing installs, and handing that
    # to a cloud provider would just produce a 404.
    if not model and name == "ollama":
        model = settings.LLM_MODEL

    # Keys live on the settings object: pydantic-settings loads .env into the
    # model, not into os.environ, so reading os.environ here would miss them.
    api_key = getattr(settings, preset.key_env, "") if preset.key_env else ""
    if preset.key_env and not api_key:
        logger.warning(
            "Provider '%s' is configured but %s is empty — it will be skipped.",
            name,
            preset.key_env,
        )
        return None

    return build_provider(name, model, api_key)


def _chain_specs() -> list[str]:
    """The configured provider chain, primary first."""
    specs = [settings.LLM_PROVIDER]
    specs += [s for s in settings.LLM_FALLBACK_PROVIDERS.split(",") if s.strip()]
    return [s for s in specs if s.strip()]


def get_chain() -> list[LLMProvider]:
    """
    Usable providers in priority order.

    Rebuilt per call rather than cached: it is cheap, and it means a corrected
    API key or model id takes effect on the next request instead of needing a
    restart.
    """
    return [p for p in (_build_provider(spec) for spec in _chain_specs()) if p is not None]


def _clean(text: str) -> str:
    """Drop reasoning scratchpads that some models emit inline."""
    return _THINK_BLOCK.sub("", text).strip()


# ═══════════════════════════════════════════════════════════════════════════
# Quota cooldowns
# ═══════════════════════════════════════════════════════════════════════════
#
# A provider that answered 429 will answer 429 again until its window rolls
# over. Free tiers count rejected calls against the same quota, so retrying
# inside that window does not just waste a request — it extends the outage.
# Remembering the deadline lets the chain skip straight to a provider that can
# actually serve, and stops a burst of concurrent requests from each
# rediscovering the limit on its own.

# quota_key -> monotonic deadline before which the provider cannot serve.
_cooldowns: dict[str, float] = {}

# Ceiling on a single cooldown. A daily quota can report a delay measured in
# hours; parking a provider that long on the strength of one response is worse
# than probing again and taking a second 429.
_MAX_COOLDOWN_SECONDS = 900.0

_EXPONENTIAL_WAIT = wait_exponential(multiplier=1, min=1, max=10)


def cooldown_remaining(provider: LLMProvider) -> float:
    """Seconds left on this provider's quota cooldown; 0.0 when it is usable."""
    deadline = _cooldowns.get(provider.quota_key)
    if deadline is None:
        return 0.0
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _cooldowns.pop(provider.quota_key, None)
        return 0.0
    return remaining


def _cooldown_seconds(error: LLMRateLimitError) -> float:
    """How long to leave a rate-limited provider alone."""
    if error.daily:
        # The provider's own delay is not believable here: Groq reports a spent
        # per-day token budget and then suggests retrying in about a minute,
        # which would have the chain rediscover the same dead provider every
        # minute until the budget resets. Probe on our own schedule instead.
        return float(settings.LLM_DAILY_QUOTA_COOLDOWN)
    if error.retry_after is not None:
        return min(float(error.retry_after), _MAX_COOLDOWN_SECONDS)
    return float(settings.LLM_RATE_LIMIT_COOLDOWN)


def _start_cooldown(provider: LLMProvider, error: LLMRateLimitError) -> None:
    """Park a rate-limited provider for as long as it is known to be unusable."""
    seconds = max(1.0, _cooldown_seconds(error))
    # Concurrent callers all discover the limit within the same instant. The
    # first one's cooldown is the one that counts; the rest would only restate
    # it, so they extend nothing and say nothing.
    if cooldown_remaining(provider) > 0:
        return

    _cooldowns[provider.quota_key] = time.monotonic() + seconds
    logger.warning(
        "Provider '%s' is over its %s quota — skipping it for the next %.0fs.",
        provider.name,
        "daily" if error.daily else "rate",
        seconds,
    )


def clear_cooldowns() -> None:
    """Forget every recorded cooldown. For tests and for an explicit re-probe."""
    _cooldowns.clear()


def _is_retryable(exc: BaseException) -> bool:
    """
    Whether another attempt against the *same* provider is worth making.

    A rate limit is only worth waiting out when the provider's own delay fits
    the budget; anything longer is answered sooner by the next provider in the
    chain, so it falls through instead of blocking the caller.
    """
    if isinstance(exc, LLMRateLimitError):
        if exc.daily:
            # A spent daily budget will still be spent a few seconds from now.
            return False
        if exc.retry_after is not None:
            return exc.retry_after <= settings.LLM_RATE_LIMIT_MAX_WAIT
    return isinstance(exc, LLMTransientError)


def _retry_wait(state: RetryCallState) -> float:
    """Honour the provider's stated delay; fall back to exponential backoff."""
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, LLMRateLimitError) and exc.retry_after is not None:
        # One extra second: the window is measured on the provider's clock, and
        # coming back a hair early costs another rejected request.
        return exc.retry_after + 1.0
    return _EXPONENTIAL_WAIT(state)


async def generate(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1000,
    top_p: Optional[float] = None,
    stop: Optional[list[str]] = None,
    timeout: float = 60.0,
    reasoning: Optional[bool] = None,
    json_mode: bool = False,
    extra: Optional[dict[str, Any]] = None,
    prefer: Optional[LLMProvider] = None,
) -> Optional[str]:
    """
    Run a completion against the configured provider chain.

    `prefer` is placed at the head of the chain, so a caller-supplied provider
    (a user's own API key) is tried first and the configured server chain acts
    as its fallback.

    Returns the response text, or None if every provider in the chain failed.
    Raises LLMRequestError if we sent a malformed request — that is our bug and
    must not be hidden behind a fallback.
    """
    req = GenerationRequest(
        prompt=prompt,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stop=stop,
        timeout=timeout,
        reasoning=reasoning,
        json_mode=json_mode,
        extra=extra or {},
    )

    chain = get_chain()
    if prefer is not None:
        chain = [prefer, *chain]
    if not chain:
        logger.error("No usable LLM provider. Set LLM_PROVIDER and the matching API key in .env.")
        return None

    # A provider still inside its quota window cannot serve this request, and
    # asking it again would only push the window further out.
    ready = [p for p in chain if cooldown_remaining(p) == 0.0]
    if not ready:
        logger.warning(
            "Every LLM provider is over quota; the first frees up in %.0fs. "
            "Answering without AI until then.",
            min(cooldown_remaining(p) for p in chain),
        )
        return None

    last_error: Optional[LLMError] = None

    def _note_failure(provider: LLMProvider, index: int, error: LLMError) -> None:
        """Record why a provider could not serve, and name the one taking over."""
        remaining = ready[index + 1 :]
        # Logged at warning either way: only the summary below is an error,
        # so one failed call produces one error line rather than two.
        if remaining:
            logger.warning(
                "LLM provider '%s' failed (%s) — falling back to '%s'",
                provider.name,
                error,
                remaining[0].name,
            )
        else:
            logger.warning(
                "LLM provider '%s' failed and no fallback remains: %s", provider.name, error
            )

    for index, provider in enumerate(ready):
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, settings.LLM_MAX_RETRIES)),
                wait=_retry_wait,
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    result = await provider.generate(req)

            # A 200 carrying no text is a failed call, not an answer. Returning
            # it here stopped the chain on a provider that had produced nothing
            # and left the caller reporting that no provider could serve the
            # request, while the configured fallbacks were never asked.
            answer = _clean(result)
            if not answer:
                last_error = LLMUnavailableError(
                    f"{provider.name}: answered with no content (model '{provider.model}')"
                )
                _note_failure(provider, index, last_error)
                continue

            if index > 0:
                logger.info("LLM served by fallback provider '%s'", provider.name)
            return answer

        except LLMRequestError:
            # Malformed request: every provider would reject it. Surface it.
            raise
        except LLMError as e:
            last_error = e
            if isinstance(e, LLMRateLimitError):
                _start_cooldown(provider, e)
            _note_failure(provider, index, e)

    logger.error("All %d LLM provider(s) failed. Last error: %s", len(ready), last_error)
    return None


async def llm_health() -> bool:
    """True if any provider in the chain can currently serve a request."""
    for provider in get_chain():
        if await provider.health():
            health.record("ai", ok=True)
            return True
    health.record("ai", ok=False, error=RuntimeError("no provider responded"))
    return False


async def active_provider_info(include_models: bool = False) -> dict[str, Any]:
    """
    Describe the configured chain for /api/llm/status.

    Never includes API keys — only whether each provider's key is present.
    """
    chain = get_chain()
    configured = _chain_specs()

    providers: list[dict[str, Any]] = []
    for provider in chain:
        cooling = cooldown_remaining(provider)
        entry: dict[str, Any] = {
            "provider": provider.name,
            "model": provider.model,
            "healthy": await provider.health(),
            # Rate-limited rather than broken: the key and model are fine, the
            # quota window simply has not rolled over yet.
            "cooldown_seconds": round(cooling, 1) if cooling else 0,
        }
        if include_models:
            entry["available_models"] = await provider.list_models()
        providers.append(entry)

    active = next((p for p in providers if p["healthy"] and not p["cooldown_seconds"]), None)

    return {
        "active": active,
        "configured_chain": configured,
        "usable_chain": providers,
        # A provider named in .env but missing from usable_chain was dropped for
        # a missing key, unknown name, or unset model — the logs say which.
        "skipped": [
            spec
            for spec in configured
            if _parse_spec(spec)[0] not in {p["provider"] for p in providers}
        ],
        "supported_providers": preset_names(),
        "ai_enabled": settings.USE_AI,
    }


__all__ = [
    "generate",
    "llm_health",
    "active_provider_info",
    "get_chain",
    "cooldown_remaining",
    "clear_cooldowns",
    "LLMError",
    "LLMRateLimitError",
    "LLMRequestError",
    "LLMTransientError",
    "LLMUnavailableError",
]
