"""
Provider-agnostic LLM interface.

Every AI feature in the app speaks this interface; the concrete providers in
`providers.py` translate it to whatever wire format their backend expects.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class GenerationRequest:
    """A single-turn completion request, expressed provider-independently."""

    prompt: str
    system: str = ""
    temperature: float = 0.7
    max_tokens: int = 1000
    top_p: Optional[float] = None
    stop: Optional[list[str]] = None
    timeout: float = 60.0
    # Whether the model may spend tokens on hidden reasoning. False is the right
    # choice for bounded/structured output (JSON, a single symbol), where
    # reasoning tokens can eat the budget before the answer is produced.
    reasoning: Optional[bool] = None
    json_mode: bool = False
    # Provider-specific knobs; each adapter picks out what it understands and
    # ignores the rest (e.g. Ollama's num_ctx / repeat_penalty).
    extra: dict[str, Any] = field(default_factory=dict)


class LLMError(Exception):
    """Base class for provider failures."""


class LLMTransientError(LLMError):
    """Worth retrying against the same provider: timeout, 429, 5xx."""


class LLMRateLimitError(LLMTransientError):
    """
    The provider refused the request on quota grounds (HTTP 429).

    `retry_after` is the delay the provider itself asked for, in seconds, when
    it supplied one. It is the only trustworthy input for backoff here: a
    free-tier per-minute quota needs tens of seconds to clear, which no
    exponential schedule starting at one second will ever reach.

    `daily` marks a budget that resets once a day rather than on a rolling
    window. Providers stay optimistic about these — Groq reports a per-day token
    limit as spent and then suggests retrying in about a minute — so the stated
    delay must not be believed, or the chain simply rediscovers the same dead
    provider every minute for the rest of the day.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None, daily: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily


class LLMUnavailableError(LLMError):
    """
    This provider cannot serve the request at all — unreachable, bad key, or
    unknown model. Retrying will not help; move to the next provider.
    """


class LLMRequestError(LLMError):
    """
    The request itself was malformed (HTTP 400). This is a bug on our side, so
    it must surface rather than being masked by a fallback provider.
    """


class LLMProvider(ABC):
    """One configured provider endpoint: a backend, a model, and credentials."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str = ""):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key

    def __repr__(self) -> str:
        # Never interpolate the API key — this ends up in logs.
        return f"<{type(self).__name__} {self.name}:{self.model}>"

    @property
    def quota_key(self) -> str:
        """
        Identifies the quota bucket this provider draws on.

        Rate limits are billed per credential, so the key is fingerprinted in:
        one user exhausting their own Gemini quota must not sideline the
        server's Gemini provider, or anyone else's.
        """
        if self._api_key:
            fingerprint = hashlib.sha256(self._api_key.encode()).hexdigest()[:12]
        else:
            fingerprint = "local"
        return f"{self.name}:{self.model}:{fingerprint}"

    @abstractmethod
    async def generate(self, req: GenerationRequest) -> str:
        """Run a completion. Raises an LLMError subclass on failure."""

    @abstractmethod
    async def health(self) -> bool:
        """True if the provider is reachable and usable right now."""

    async def list_models(self) -> list[str]:
        """Model ids this provider offers, or an empty list if unsupported."""
        return []
