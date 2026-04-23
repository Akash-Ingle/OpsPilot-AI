"""Production-ready LLM client for the OpsPilot-AI agent.

Design goals:
- Provider-agnostic public API: `call_llm(system_prompt, user_prompt) -> dict`.
- Easily swappable backends (Anthropic / OpenAI) selected via `settings.llm_provider`.
- Forces JSON output on both providers.
- Validates the response against `LLMStructuredOutput` (app/schemas/analysis.py).
- Retries up to `settings.llm_max_retries` on parse / validation failures, with a
  corrective nudge appended to the user prompt each retry.
- Uniform timeout + error handling.
- Structured logging via loguru.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, Dict, Optional

from pydantic import ValidationError

from app.config import settings
from app.core.logging import logger
from app.schemas.analysis import LLMStructuredOutput


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base error for any LLM-related failure."""


class LLMTimeoutError(LLMError):
    """Raised when the provider call exceeds the configured timeout."""


class LLMValidationError(LLMError):
    """Raised when the model output cannot be parsed/validated after all retries."""

    def __init__(self, message: str, *, last_raw: str | None = None, errors: list[str] | None = None):
        super().__init__(message)
        self.last_raw = last_raw
        self.errors = errors or []


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract provider: one method, returns raw assistant text."""

    name: str = "base"

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send prompts to the provider and return the raw text response."""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise LLMError("anthropic package is not installed") from exc

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Reinforce JSON-only output; Anthropic has no explicit JSON mode, so we
        # rely on clear instructions plus assistant prefill of "{" to anchor the
        # response as JSON.
        system = system_prompt.rstrip() + "\n\nRespond with a single JSON object. No prose, no markdown fences."

        try:
            response = self._client.messages.create(
                model=settings.llm_model,
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
                system=system,
                messages=[
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": "{"},
                ],
            )
        except self._anthropic.APITimeoutError as exc:
            raise LLMTimeoutError(f"Anthropic request timed out: {exc}") from exc
        except self._anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        # Re-attach the prefill "{" so the text is a complete JSON object.
        return "{" + "".join(parts)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        try:
            import openai  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise LLMError("openai package is not installed") from exc

        self._openai = openai
        self._client = openai.OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # OpenAI's JSON mode requires the word "json" somewhere in the messages.
        user = user_prompt
        if "json" not in (system_prompt + user).lower():
            user += "\n\n(Respond in JSON.)"

        try:
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                ],
            )
        except self._openai.APITimeoutError as exc:
            raise LLMTimeoutError(f"OpenAI request timed out: {exc}") from exc
        except self._openai.APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc

        return response.choices[0].message.content or ""


@lru_cache(maxsize=1)
def _get_provider() -> LLMProvider:
    """Return a cached provider instance selected by configuration."""
    provider_name = (settings.llm_provider or "").strip().lower()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    raise LLMError(
        f"Unsupported LLM provider: {settings.llm_provider!r}. Use 'anthropic' or 'openai'."
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> Optional[str]:
    """Best-effort extraction of a JSON object from a raw model response."""
    if not raw:
        return None

    text = raw.strip()

    # Strip common markdown code fences.
    fence = _CODE_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    match = _JSON_OBJECT_RE.search(text)
    return match.group(0) if match else None


_ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
_ALLOWED_ACTIONS = {
    "fetch_logs",
    "get_metrics",
    "restart_service",
    "scale_service",
    "none",
}


def _salvage_partial(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Best-effort fixup for partially-invalid LLM output.

    The essential diagnostic fields (`issue`, `root_cause`, `fix`) must be
    present and non-empty strings. Everything else is coerced or defaulted:

    - severity: lowercased / defaulted to "medium" when unknown.
    - confidence: coerced to float, clamped to [0.0, 1.0], defaulted to 0.5.
    - needs_more_data: coerced to bool, defaulted to False.
    - requested_action: defaulted to "none" when unknown.
    - requested_action_args: coerced to dict, defaulted to {}.

    Returns None if the result still cannot be validated.
    """
    if not isinstance(obj, dict):
        return None

    for key in ("issue", "root_cause", "fix"):
        val = obj.get(key)
        if not isinstance(val, str) or not val.strip():
            return None

    fixed: Dict[str, Any] = dict(obj)

    sev = str(fixed.get("severity", "")).lower().strip()
    fixed["severity"] = sev if sev in _ALLOWED_SEVERITIES else "medium"

    try:
        conf = float(fixed.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    fixed["confidence"] = max(0.0, min(1.0, conf))

    fixed["needs_more_data"] = bool(fixed.get("needs_more_data", False))

    action = fixed.get("requested_action")
    if action not in _ALLOWED_ACTIONS:
        fixed["requested_action"] = "none"

    args = fixed.get("requested_action_args", {})
    fixed["requested_action_args"] = args if isinstance(args, dict) else {}

    # reasoning_steps: coerce strings, drop empty entries, fallback to a
    # synthesized single-step explanation so downstream consumers always get
    # *something* to show. We do NOT hallucinate real reasoning here.
    raw_steps = fixed.get("reasoning_steps")
    steps: list[str] = []
    if isinstance(raw_steps, list):
        for item in raw_steps:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    steps.append(text[:500])
    if not steps:
        steps = [
            "Model did not provide explicit reasoning; diagnosis returned "
            "without a step-by-step trace."
        ]
    fixed["reasoning_steps"] = steps

    # relevant_log_lines: filter out entries that can't be validated rather
    # than failing the whole response. Keep only well-formed references.
    raw_refs = fixed.get("relevant_log_lines")
    refs: list[Dict[str, Any]] = []
    if isinstance(raw_refs, list):
        for ref in raw_refs:
            if not isinstance(ref, dict):
                continue
            has_id = isinstance(ref.get("log_id"), int)
            has_idx = isinstance(ref.get("line_index"), int) and int(ref["line_index"]) >= 1
            has_excerpt = isinstance(ref.get("excerpt"), str) and ref["excerpt"].strip()
            if has_id or has_idx or has_excerpt:
                refs.append(ref)
    fixed["relevant_log_lines"] = refs

    try:
        return LLMStructuredOutput.model_validate(fixed).model_dump(mode="json")
    except ValidationError:
        return None


def _parse_and_validate(
    raw: str,
    *,
    allow_salvage: bool = False,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (validated_dict, error_message). Exactly one is non-None.

    When `allow_salvage` is True and strict validation fails, a best-effort
    fixup is attempted before declaring failure.
    """
    candidate = _extract_json_object(raw)
    if not candidate:
        return None, "response did not contain a JSON object"

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"

    if not isinstance(obj, dict):
        return None, f"expected a JSON object, got {type(obj).__name__}"

    try:
        validated = LLMStructuredOutput.model_validate(obj)
        return validated.model_dump(mode="json"), None
    except ValidationError as exc:
        if allow_salvage:
            salvaged = _salvage_partial(obj)
            if salvaged is not None:
                logger.warning("LLM output salvaged with best-effort defaults")
                return salvaged, None
        return None, f"schema validation failed: {exc.errors()}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call_llm(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """Call the configured LLM and return a validated structured-output dict.

    Args:
        system_prompt: System-role instructions (e.g. `SYSTEM_PROMPT`).
        user_prompt: User-role content (e.g. logs + anomalies summary).

    Returns:
        A dict matching `LLMStructuredOutput`.

    Raises:
        LLMError: The provider is misconfigured or the API errored out.
        LLMTimeoutError: The provider exceeded the configured timeout.
        LLMValidationError: The model response could not be parsed/validated
            after all retries.
    """
    provider = _get_provider()
    max_retries = max(0, int(settings.llm_max_retries))
    attempts = max_retries + 1

    current_user = user_prompt
    errors: list[str] = []
    last_raw: str | None = None

    for attempt in range(1, attempts + 1):
        logger.debug(
            "LLM call attempt {}/{} via provider={} model={}",
            attempt,
            attempts,
            provider.name,
            settings.llm_model,
        )

        raw = provider.complete(system_prompt, current_user)
        last_raw = raw

        # Only allow best-effort salvage on the final attempt - earlier attempts
        # should pressure the model into producing clean JSON via the retry nudge.
        is_last_attempt = attempt == attempts
        validated, err = _parse_and_validate(raw, allow_salvage=is_last_attempt)
        if validated is not None:
            logger.info(
                "LLM call succeeded on attempt {}/{} (provider={})",
                attempt,
                attempts,
                provider.name,
            )
            return validated

        errors.append(f"attempt {attempt}: {err}")
        logger.warning(
            "LLM response invalid on attempt {}/{}: {} | raw_preview={!r}",
            attempt,
            attempts,
            err,
            (raw or "")[:200],
        )

        if attempt < attempts:
            # Nudge the model with an explicit correction on the next attempt.
            current_user = (
                f"{user_prompt}\n\n"
                f"Your previous response was rejected: {err}. "
                "Return ONLY a single valid JSON object that matches the required schema. "
                "No prose, no markdown, no code fences."
            )

    raise LLMValidationError(
        f"LLM failed to return valid structured output after {attempts} attempts",
        last_raw=last_raw,
        errors=errors,
    )


__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "LLMValidationError",
    "LLMProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "call_llm",
]
