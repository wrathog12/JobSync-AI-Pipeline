"""Gemini implementation of `LLMClient`, via the `google-genai` SDK (v2.x).

Written against the surface actually present in google-genai 2.22: `response.parsed`
for schema-validated output, `usage_metadata.thoughts_token_count` for the
reasoning bill, and `errors.ClientError` / `errors.ServerError` for status
mapping. Verified rather than assumed.

Two things get careful handling because they are silent failures:

* **Truncation.** Hitting `max_output_tokens` returns `finish_reason=MAX_TOKENS`
  with a *partial* answer and no exception. A half-sentence cover letter that
  looks complete is worse than an error, so it is flagged on the response.
* **Safety blocks.** A refused request returns no candidate at all, and naive
  code reads `response.text` and gets an empty string. That would look like the
  model declining to answer, which we would then store as a real answer.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import (
    LLMAuthError,
    LLMBlockedError,
    LLMCall,
    LLMProviderError,
    LLMQuotaError,
    LLMResponse,
    LLMSchemaError,
    LLMUsage,
    Timer,
)
from .keys import resolve_key

#: Retry backoff. Short because a form fill is interactive — and on BYOK a long
#: retry chain quietly multiplies the user's bill for one field.
_BACKOFF_S = (0.5, 1.5)


class GeminiClient:
    """One client per key. Cheap to construct; holds no conversation state."""

    def __init__(self, api_key: str | None = None) -> None:
        # Resolved here so a bad key fails at construction with a clear message,
        # rather than inside the pipeline three stages later.
        self._key = resolve_key(api_key)
        self._settings = get_settings()
        self._client: Any = None

    @property
    def client(self) -> Any:
        """Built lazily: importing the SDK costs ~200ms, and tests that never call
        out should not pay it."""
        if self._client is None:
            from google import genai
            from google.genai import types as gt

            self._client = genai.Client(
                api_key=self._key,
                http_options=gt.HttpOptions(timeout=int(self._settings.llm_timeout_s * 1000)),
            )
        return self._client

    # ── public API ─────────────────────────────────────────────────────────────

    def generate(self, call: LLMCall) -> LLMResponse:
        model = call.model or self._settings.llm_model_fast
        config = self._build_config(call)

        retries = self._settings.llm_max_retries
        for attempt in range(1, retries + 2):
            try:
                with Timer() as t:
                    raw = self.client.models.generate_content(
                        model=model, contents=call.prompt, config=config
                    )
                return self._to_response(raw, model=model, call=call, ms=t.ms, attempts=attempt)
            except Exception as exc:  # noqa: BLE001 — mapped, then re-raised
                # Map BEFORE deciding whether to retry: the SDK raises its own
                # exception types, so a loop that tested for `LLMQuotaError` on the
                # way in would never match and `llm_max_retries` would be dead
                # configuration.
                err = self._map_error(exc)
                # Retry transient failures only. Auth, safety, and schema errors
                # are deterministic — retrying spends the user's money for the
                # same result.
                if attempt > retries or not getattr(err, "retryable", False):
                    raise err from exc
                time.sleep(_BACKOFF_S[min(attempt - 1, len(_BACKOFF_S) - 1)])

        raise AssertionError("unreachable: the loop either returns or raises")

    def list_models(self) -> list[str]:
        """What this key can actually reach.

        Worth calling rather than trusting `llm_model_fast`: model names get
        retired, and "404 model not found" on the user's first upload is a bad
        first impression of a BYOK product.
        """
        try:
            out: list[str] = []
            for m in self.client.models.list():
                name = (getattr(m, "name", "") or "").removeprefix("models/")
                actions = getattr(m, "supported_actions", None)
                if name and (not actions or "generateContent" in actions):
                    out.append(name)
            return sorted(out)
        except Exception as exc:  # noqa: BLE001
            raise self._map_error(exc) from exc

    # ── internals ──────────────────────────────────────────────────────────────

    def _build_config(self, call: LLMCall) -> Any:
        from google.genai import types as gt

        s = self._settings
        kwargs: dict[str, Any] = {
            "max_output_tokens": call.max_output_tokens or s.llm_max_output_tokens,
        }
        if call.system:
            kwargs["system_instruction"] = call.system
        if call.temperature is not None:
            kwargs["temperature"] = call.temperature
        if call.stop_sequences:
            kwargs["stop_sequences"] = call.stop_sequences

        if call.schema is not None:
            # Server-side schema enforcement is the point. The tier-2 classifier's
            # invariant — the model returns a KEY from a closed list, never a
            # value — is only a guarantee if the provider enforces it.
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = call.schema

        budget = call.thinking_budget
        if budget is None and call.schema is not None:
            # Structuring and tagging are extraction, not reasoning. Thinking
            # tokens there are billed output the user never sees.
            budget = s.thinking_budget_fast
        if budget is not None:
            kwargs["thinking_config"] = gt.ThinkingConfig(thinking_budget=budget)

        return gt.GenerateContentConfig(**kwargs)

    def _to_response(
        self, raw: Any, *, model: str, call: LLMCall, ms: int, attempts: int
    ) -> LLMResponse:
        self._check_blocked(raw)

        candidate = (getattr(raw, "candidates", None) or [None])[0]
        finish = getattr(candidate, "finish_reason", None)
        finish_name = getattr(finish, "name", None) or (str(finish) if finish else None)

        text = getattr(raw, "text", None) or ""
        usage = _usage_of(raw)
        truncated = finish_name == "MAX_TOKENS"

        parsed: BaseModel | None = None
        if call.schema is not None:
            parsed = self._parse(raw, text, call.schema, truncated=truncated)

        return LLMResponse(
            text=text,
            parsed=parsed,
            usage=usage,
            model=model,
            finish_reason=finish_name,
            ms=ms,
            attempts=attempts,
            truncated=truncated,
        )

    def _parse(
        self, raw: Any, text: str, schema: type[BaseModel], *, truncated: bool
    ) -> BaseModel:
        """Validate, and fail closed. Never return a half-built record."""
        parsed = getattr(raw, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        if truncated:
            raise LLMSchemaError(
                "The model's response was cut off before it was complete. "
                "Try again with a shorter document, or a smaller section of it.",
                detail=f"MAX_TOKENS with {len(text)} chars of partial JSON",
            )

        # The SDK leaves `.parsed` as None when the JSON is well-formed but does
        # not fit the schema, so fall back to explicit validation to get a real
        # error message instead of a bare None.
        if text.strip():
            try:
                return schema.model_validate_json(text)
            except ValidationError as exc:
                raise LLMSchemaError(
                    "The model returned data in an unexpected shape, so nothing "
                    "was saved. This is a bug on our side, not yours.",
                    detail=str(exc)[:800],
                ) from exc

        raise LLMSchemaError(
            "The model returned an empty response.",
            detail=f"finish_reason={getattr(raw, 'candidates', None) and 'see trace'}",
        )

    @staticmethod
    def _check_blocked(raw: Any) -> None:
        """Turn a safety refusal into a clear error, not an empty answer."""
        feedback = getattr(raw, "prompt_feedback", None)
        block = getattr(feedback, "block_reason", None)
        if block:
            name = getattr(block, "name", None) or str(block)
            raise LLMBlockedError(
                "Gemini declined to process this text. If your résumé covers "
                "defense, medical, or security work, its filters sometimes "
                "misfire — you can write this answer yourself and we'll remember it.",
                detail=f"prompt block_reason={name}",
            )

        candidates = getattr(raw, "candidates", None) or []
        if not candidates:
            raise LLMBlockedError(
                "Gemini returned no response for this request.",
                detail="no candidates and no block_reason",
            )

        finish = getattr(candidates[0], "finish_reason", None)
        name = getattr(finish, "name", None) or (str(finish) if finish else "")
        if name in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}:
            raise LLMBlockedError(
                "Gemini blocked its own answer to this question on content "
                "grounds. Write it yourself and we'll reuse it from now on.",
                detail=f"finish_reason={name}",
            )
        if name == "RECITATION":
            raise LLMBlockedError(
                "Gemini stopped because its answer was reproducing source text "
                "too closely. Try rephrasing the question.",
                detail="finish_reason=RECITATION",
            )

    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        """HTTP status -> our taxonomy, so BYOK blame lands on the right party."""
        from google.genai import errors as ge

        if isinstance(exc, (LLMAuthError, LLMQuotaError, LLMProviderError, LLMBlockedError,
                            LLMSchemaError)):
            return exc

        if isinstance(exc, ge.APIError):
            code = getattr(exc, "code", None)
            message = (getattr(exc, "message", None) or str(exc))[:400]

            if code in (401, 403):
                return LLMAuthError(
                    "Your Gemini API key was rejected. Check it at "
                    "aistudio.google.com/apikey, and that the Generative Language "
                    "API is enabled for its project.",
                    detail=message,
                )
            if code == 429:
                return LLMQuotaError(
                    "Your Gemini key is out of quota or rate-limited right now. "
                    "Free-tier keys have low per-minute limits — wait a moment, or "
                    "enable billing on the key's project.",
                    detail=message,
                )
            if code == 404:
                return LLMAuthError(
                    "Your key cannot reach the requested model. It may have been "
                    "retired, or not be available on your plan.",
                    detail=message,
                )
            if code == 400:
                # Careful: Google reports an invalid API key as 400
                # INVALID_ARGUMENT with reason API_KEY_INVALID, *not* 401. Verified
                # against the live API. Treating every 400 as our bug would tell a
                # user who mistyped their key that we broke, which is the wrong
                # party and sends them looking in the wrong place.
                if _reason_of(exc) == "API_KEY_INVALID" or "api key not valid" in message.lower():
                    return LLMAuthError(
                        "That Gemini API key was rejected. Copy it again from "
                        "aistudio.google.com/apikey.",
                        detail=message,
                    )
                # Otherwise it really is our prompt or schema.
                return LLMSchemaError(
                    "We sent Gemini a malformed request. This is a bug on our side.",
                    detail=message,
                )
            if isinstance(exc, ge.ServerError) or (code and code >= 500):
                return LLMProviderError(
                    "Gemini is having trouble right now. Try again shortly.",
                    detail=message,
                )
            return LLMProviderError(f"Gemini returned an error ({code}).", detail=message)

        name = type(exc).__name__
        if "Timeout" in name or "timeout" in str(exc).lower():
            return LLMProviderError(
                "Gemini took too long to respond. Try again.", detail=name
            )
        if "Connect" in name or "SSL" in name:
            return LLMProviderError(
                "Could not reach Gemini. Check your internet connection.", detail=name
            )
        return LLMProviderError(f"Unexpected error talking to Gemini ({name}).",
                                detail=str(exc)[:400])


def _reason_of(exc: Any) -> str | None:
    """The machine-readable `reason` Google buries in `error.details`.

    Worth digging for rather than matching on prose: the human message is
    localized and gets reworded, the reason code does not.
    """
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    for item in (details.get("error") or {}).get("details") or []:
        if isinstance(item, dict) and item.get("reason"):
            return str(item["reason"])
    return None


def _usage_of(raw: Any) -> LLMUsage:
    """Token counts, defensively — a missing usage block must not crash a fill."""
    u = getattr(raw, "usage_metadata", None)
    if u is None:
        return LLMUsage()
    return LLMUsage(
        prompt_tokens=getattr(u, "prompt_token_count", 0) or 0,
        output_tokens=getattr(u, "candidates_token_count", 0) or 0,
        cached_tokens=getattr(u, "cached_content_token_count", 0) or 0,
        thinking_tokens=getattr(u, "thoughts_token_count", 0) or 0,
    )


def get_client(api_key: str | None = None) -> GeminiClient:
    """Per-request client. Deliberately NOT cached by key.

    Caching clients keyed by API key would hold users' keys in a process-global
    dict for the lifetime of the server, which is exactly what BYOK promises not
    to do. Construction is cheap; the SDK import is what costs, and that is
    module-level and shared.
    """
    return GeminiClient(api_key)


__all__ = ["GeminiClient", "get_client"]
