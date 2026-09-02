"""LLM access. Provider-neutral interface, Gemini implementation, BYOK key seam.

    call = LLMCall(prompt=..., schema=SomeModel, label="structure")
    res  = get_client(user_api_key).generate(call)
    res.parsed   # a validated SomeModel, or the call raised

Three rules this package exists to enforce:

* **The key is never global.** It arrives per request and is resolved in one
  place (`keys.resolve_key`). See config.py for why that matters.
* **Schema-first.** `generate()` validates against a Pydantic model and fails
  closed. Unvalidated output must never reach L0-L2.
* **Failures are attributed.** `LLMError.blame` says whether the user's key, the
  provider, our code, or a content filter is responsible — because on BYOK
  "quota exceeded" is not an outage and must not read like one.
"""

from .base import (
    Blame,
    LLMAuthError,
    LLMBlockedError,
    LLMCall,
    LLMClient,
    LLMError,
    LLMProviderError,
    LLMQuotaError,
    LLMResponse,
    LLMSchemaError,
    LLMUsage,
)
from .fake import FakeClient
from .gemini import GeminiClient, get_client
from .keys import has_server_key, redact, resolve_key

__all__ = [
    "Blame",
    "LLMCall",
    "LLMClient",
    "LLMResponse",
    "LLMUsage",
    "LLMError",
    "LLMAuthError",
    "LLMQuotaError",
    "LLMProviderError",
    "LLMBlockedError",
    "LLMSchemaError",
    "GeminiClient",
    "get_client",
    "FakeClient",
    "resolve_key",
    "has_server_key",
    "redact",
]
