"""
Concrete LLM provider adapters.

Three are enough to cover the field: almost every cloud provider speaks the
OpenAI chat-completions format, Anthropic has its own, and Ollama has its own.
"""

import json
import logging
import re
from typing import Any, Optional

import httpx

from config import settings
from services.llm.base import (
    GenerationRequest,
    LLMProvider,
    LLMRateLimitError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

# Google returns its quota delay twice: once as a structured RetryInfo detail
# and once as prose inside the message. Either will do, so both are matched.
_RETRY_DELAY_FIELD = re.compile(r'"retryDelay"\s*:\s*"([0-9]+(?:\.[0-9]+)?)s"')
_RETRY_DELAY_PROSE = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)

# Bounds a single log line. Provider error envelopes run to kilobytes of quota
# metadata and documentation links; none of it belongs in the log.
_DETAIL_LIMIT = 300

# A quota that resets once a day rather than on a rolling window: Groq's TPD/RPD
# ("tokens per day"), Google's free-tier daily request cap. Matched on the error
# text because no provider exposes the distinction as a field.
_DAILY_QUOTA = re.compile(r"per\s+day|\bTPD\b|\bRPD\b|\bdaily\b", re.IGNORECASE)


def _error_detail(response: httpx.Response) -> str:
    """
    A one-line, bounded description of a failed response.

    Only the provider's own error message is kept. Logging the raw body would
    dump the full envelope — including any request content the provider echoes
    back — into the log, which the project's LLM rules forbid.
    """
    try:
        payload: Any = response.json()
    except ValueError:
        return " ".join(response.text.split())[:_DETAIL_LIMIT]

    # Gemini's OpenAI-compatible shim wraps the envelope in a list.
    if isinstance(payload, list):
        payload = payload[0] if payload else {}

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, str):
        return " ".join(error.split())[:_DETAIL_LIMIT]
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or error.get("type")
        if message:
            return " ".join(str(message).split())[:_DETAIL_LIMIT]

    return " ".join(response.text.split())[:_DETAIL_LIMIT]


def _retry_after(response: httpx.Response) -> Optional[float]:
    """
    How long the provider asked us to wait, in seconds, or None if it did not say.

    Checked against the header first because it is the standard; providers that
    only state the delay in the error body are covered by the patterns below.
    """
    header = response.headers.get("retry-after", "").strip()
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            # The HTTP-date form. Providers that use it also repeat the delay in
            # the body, so fall through rather than pull in a date parser.
            pass

    body = response.text
    for pattern in (_RETRY_DELAY_FIELD, _RETRY_DELAY_PROSE):
        match = pattern.search(body)
        if match:
            return float(match.group(1))
    return None


def _raise_for_status(provider: str, response: httpx.Response) -> None:
    """
    Translate an HTTP failure into the error class that drives retry/fallback.

    The distinction matters: a 429 should be retried on the provider's own
    schedule, a bad API key should skip straight to the next provider, and a
    400 is our own bug and must not be quietly masked by a fallback.
    """
    status = response.status_code
    if status < 400:
        return

    detail = _error_detail(response)

    if status == 400:
        raise LLMRequestError(f"{provider}: malformed request (400) — {detail}")
    if status in (401, 403):
        raise LLMUnavailableError(
            f"{provider}: authentication failed ({status}) — check the API key"
        )
    if status == 404:
        raise LLMUnavailableError(f"{provider}: model or endpoint not found (404) — {detail}")
    if status == 429:
        raise LLMRateLimitError(
            f"{provider}: rate limited (429) — {detail}",
            _retry_after(response),
            daily=bool(_DAILY_QUOTA.search(detail)),
        )
    if status >= 500:
        raise LLMTransientError(f"{provider}: HTTP {status} — {detail}")
    raise LLMUnavailableError(f"{provider}: HTTP {status} — {detail}")


async def _post(provider: str, url: str, *, json: dict, headers: dict, timeout: float) -> dict:
    """POST helper that maps network faults onto the retry/fallback taxonomy."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=json, headers=headers)
    except httpx.TimeoutException as e:
        raise LLMTransientError(f"{provider}: request timed out after {timeout}s") from e
    except httpx.ConnectError as e:
        raise LLMUnavailableError(f"{provider}: cannot connect to {url}") from e
    except httpx.HTTPError as e:
        raise LLMTransientError(f"{provider}: transport error — {e}") from e

    _raise_for_status(provider, response)
    return response.json()


# ═══════════════════════════════════════════════════════════════════════════
# OpenAI-compatible (Groq, Gemini, OpenAI, OpenRouter, DeepSeek, xAI, …)
# ═══════════════════════════════════════════════════════════════════════════


class OpenAICompatProvider(LLMProvider):
    """
    Any backend exposing POST /chat/completions in OpenAI's format.

    Gemini is included here: Google publishes an OpenAI-compatible endpoint and
    maps `reasoning_effort` onto its own thinking levels, so it needs no special
    casing.
    """

    async def generate(self, req: GenerationRequest) -> str:
        messages: list[dict[str, str]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": False,
        }
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.stop:
            payload["stop"] = req.stop
        if req.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if req.reasoning is False:
            # Support for this is uneven even within one provider: Groq's Qwen
            # models and Gemini accept "none", but Groq's gpt-oss only takes
            # low/medium/high and its Llama models reject the field outright.
            # We ask for it optimistically and drop it if the model complains —
            # the same approach used for Ollama's `think` flag.
            payload["reasoning_effort"] = "none"

        url = f"{self.base_url}/chat/completions"
        try:
            data = await _post(
                self.name, url, json=payload, headers=self._headers(), timeout=req.timeout
            )
        except LLMRequestError as e:
            if "reasoning_effort" not in payload or "reasoning_effort" not in str(e):
                raise
            payload.pop("reasoning_effort")
            logger.debug("%s: model rejected reasoning_effort; retrying without it", self.name)
            data = await _post(
                self.name, url, json=payload, headers=self._headers(), timeout=req.timeout
            )

        choices = data.get("choices") or []
        if not choices:
            raise LLMTransientError(f"{self.name}: response contained no choices")
        return (choices[0].get("message", {}).get("content") or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code != 200:
                return []
            return sorted(
                m["id"]
                for m in response.json().get("data", [])
                if isinstance(m, dict) and m.get("id")
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return []


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic (native /v1/messages)
# ═══════════════════════════════════════════════════════════════════════════


class AnthropicProvider(LLMProvider):
    """Anthropic's Messages API: system is a top-level field, max_tokens required."""

    API_VERSION = "2023-06-01"
    JSON_TOOL_NAME = "emit_json"

    async def generate(self, req: GenerationRequest) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            payload["system"] = req.system
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.stop:
            payload["stop_sequences"] = req.stop
        if req.json_mode:
            # Anthropic has no `response_format`; a forced tool call is the
            # schema equivalent. Without this the model answers in prose and
            # every JSON stage falls back to brace-slicing the response.
            payload["tools"] = [
                {
                    "name": self.JSON_TOOL_NAME,
                    "description": "Return the answer as a single JSON object.",
                    "input_schema": {"type": "object", "additionalProperties": True},
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": self.JSON_TOOL_NAME}

        data = await _post(
            self.name,
            f"{self.base_url}/messages",
            json=payload,
            headers=self._headers(),
            timeout=req.timeout,
        )

        blocks = [b for b in data.get("content", []) if isinstance(b, dict)]

        # A forced tool call carries the answer in `input`, not in a text block.
        # This has to be checked first: the text filter below drops `tool_use`
        # blocks, so a forced response would otherwise come back empty.
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") == self.JSON_TOOL_NAME:
                return json.dumps(block.get("input") or {})

        # Otherwise content is a list of blocks; concatenate the text ones and
        # drop the rest (thinking blocks, tool calls) so callers get plain prose.
        parts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
        return "".join(parts).strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
        }

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code != 200:
                return []
            return sorted(m["id"] for m in response.json().get("data", []) if m.get("id"))
        except (httpx.HTTPError, ValueError, KeyError):
            return []


# ═══════════════════════════════════════════════════════════════════════════
# Ollama (native /api/generate)
# ═══════════════════════════════════════════════════════════════════════════


class OllamaProvider(LLMProvider):
    """Local Ollama. Keeps the model-not-pulled diagnostics that used to live in
    ai_service, since that is by far the most common local failure."""

    async def generate(self, req: GenerationRequest) -> str:
        options: dict[str, Any] = {
            "temperature": req.temperature,
            "num_predict": req.max_tokens,
        }
        if req.top_p is not None:
            options["top_p"] = req.top_p
        if req.stop:
            options["stop"] = req.stop
        # num_ctx, repeat_penalty and friends ride along untouched.
        options.update(req.extra or {})

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": req.prompt,
            "system": req.system,
            "stream": False,
            "options": options,
            # Ollama evicts an idle model after five minutes and reloading a
            # large one costs tens of seconds — long enough that every call
            # racing the reload times out. Holding it resident trades memory
            # for that stall.
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
        }
        if req.json_mode:
            payload["format"] = "json"
        if req.reasoning is not None:
            payload["think"] = req.reasoning

        url = f"{self.base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=req.timeout) as client:
                response = await client.post(url, json=payload)

                # Models without reasoning support reject the `think` flag;
                # retry once without it so switching to a non-thinking model
                # never hard-fails.
                if (
                    response.status_code == 400
                    and "think" in payload
                    and "think" in response.text.lower()
                ):
                    payload.pop("think")
                    response = await client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise LLMTransientError(f"{self.name}: request timed out after {req.timeout}s") from e
        except httpx.ConnectError as e:
            raise LLMUnavailableError(
                f"{self.name}: Ollama is not reachable at {self.base_url} — is `ollama serve` running?"
            ) from e
        except httpx.HTTPError as e:
            raise LLMTransientError(f"{self.name}: transport error — {e}") from e

        if response.status_code == 404:
            raise LLMUnavailableError(
                f"{self.name}: model '{self.model}' is not installed. Run: ollama pull {self.model}"
            )
        _raise_for_status(self.name, response)

        body = response.json()
        self._log_token_usage(req, body)

        answer = (body.get("response") or "").strip()
        if answer:
            return answer

        # `format: json` constrains the *whole* generation, and a thinking model
        # spends that constrained budget on its thinking channel: the JSON comes
        # back complete under `thinking` with `response` empty and done_reason
        # "stop". Discarding it would fail a stage the model actually answered,
        # so the thinking text is taken as the answer when there is no other.
        thinking = (body.get("thinking") or "").strip()
        if thinking:
            logger.warning(
                "%s: model '%s' returned an empty response and answered on the thinking "
                "channel — using that. This happens with json_mode on a thinking model.",
                self.name,
                self.model,
            )
        return thinking

    def _log_token_usage(self, req: GenerationRequest, body: dict) -> None:
        """
        Record what the server actually read, so truncation stops being invisible.

        Ollama drops the front of an over-long prompt without saying so — the only
        evidence is `prompt_eval_count` coming back smaller than what was sent.
        Since `/api/generate` renders `system` first, the tokens lost are the
        system prompt's, which is where the anti-hallucination rules live. Logging
        the real count is also what lets `prompt_budget.estimate_tokens` be
        re-calibrated against production traffic instead of a synthetic probe.
        """
        prompt_tokens = body.get("prompt_eval_count")
        if not isinstance(prompt_tokens, int):
            return

        from services.prompt_budget import estimate_tokens

        sent = estimate_tokens(req.system or "") + estimate_tokens(req.prompt)
        logger.info(
            "%s: prompt_eval=%d output=%s (estimated %d sent, num_ctx=%s)",
            self.name,
            prompt_tokens,
            body.get("eval_count", "?"),
            sent,
            (req.extra or {}).get("num_ctx", "server default"),
        )
        # A generous margin: the estimator over-counts prose, so a small shortfall
        # is expected and only a large one means the server dropped input.
        if sent > 1.4 * prompt_tokens and sent - prompt_tokens > 500:
            logger.warning(
                "%s: prompt looks TRUNCATED — sent ~%d tokens, server evaluated %d. "
                "The system prompt is cut first. Lower PROMPT_TOKEN_BUDGET.",
                self.name,
                sent,
                prompt_tokens,
            )

    async def health(self) -> bool:
        return await self._tags() is not None

    async def list_models(self) -> list[str]:
        tags = await self._tags()
        if not tags:
            return []
        return sorted(m["name"] for m in tags.get("models", []) if m.get("name"))

    async def _tags(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None


ADAPTERS: dict[str, type[LLMProvider]] = {
    "openai_compat": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}
