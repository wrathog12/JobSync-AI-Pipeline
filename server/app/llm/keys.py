"""Key resolution for BYOK. The one place a key is chosen.

Rules, in order:

1. A key on the request wins. That is the production path — the user's key,
   travelling with their request, used once, never written down.
2. Otherwise the server's own `GEMINI_API_KEY`, which exists so development
   works without pasting a key into every call.
3. `require_user_key=true` disables step 2 entirely. Production sets it, so a
   misconfigured deploy fails loudly instead of quietly billing us for every
   user.

**Nothing else in the codebase may read `settings.gemini_api_key`.** A module
that captures a key at import time cannot serve two users with two keys, and
finding every such capture later is the expensive kind of refactor.
"""

from __future__ import annotations

from ..config import get_settings
from .base import LLMAuthError

#: Google API keys are ~39 chars starting "AIza". We check the shape only to give
#: a useful error for an obvious paste accident (a truncated key, a whole curl
#: command, an OpenAI key). Real validation is the provider's job — guessing
#: harder here would reject valid keys after a format change.
_MIN_KEY_LEN = 20


def resolve_key(request_key: str | None = None) -> str:
    """The key to use for one call, or raise `LLMAuthError` explaining what to do."""
    settings = get_settings()

    key = (request_key or "").strip()
    if key:
        _sanity_check(key)
        return key

    if settings.require_user_key:
        raise LLMAuthError(
            "No API key was supplied with this request. JobSync uses your own "
            "Gemini key — add it in settings."
        )

    fallback = (settings.gemini_api_key or "").strip()
    if fallback:
        return fallback

    raise LLMAuthError(
        "No Gemini API key configured. Add GEMINI_API_KEY to server/.env for "
        "development, or supply the user's key with the request."
    )


def _sanity_check(key: str) -> None:
    if len(key) < _MIN_KEY_LEN or " " in key or "\n" in key:
        raise LLMAuthError(
            "That doesn't look like a Gemini API key. Copy it from "
            "aistudio.google.com/apikey — it should be a single line with no spaces."
        )
    if key.startswith("sk-"):
        raise LLMAuthError(
            "That looks like an OpenAI key. JobSync needs a Gemini key from "
            "aistudio.google.com/apikey."
        )


def has_server_key() -> bool:
    """For /meta/llm: says whether dev fallback is available, never the key."""
    settings = get_settings()
    return not settings.require_user_key and bool((settings.gemini_api_key or "").strip())


def redact(key: str | None) -> str:
    """Last four characters only. Logs and traces must never carry a whole key."""
    if not key:
        return "(none)"
    return f"…{key[-4:]}" if len(key) > 4 else "(set)"


__all__ = ["resolve_key", "has_server_key", "redact"]
