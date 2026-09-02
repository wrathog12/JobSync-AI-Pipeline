"""Provider-neutral LLM interface, usage accounting, and the error taxonomy.

Three call sites use this, and they want different things:

  * **structuring** (step 3) — one big schema, runs once per document
  * **tagging** (step 5)     — a closed list of competency tags, per chunk
  * **generation** (step 6)  — prose, with the grounding check downstream

So the interface is schema-first: `generate()` takes a Pydantic model and returns
a validated instance. Free-text generation is the special case (`schema=None`),
not the default. That inversion is deliberate — the classifier's core invariant is
that the model picks a KEY from a closed list and never emits the value, and a
server-enforced schema is what makes that a guarantee rather than a hope.

**The error taxonomy exists because of BYOK.** When the user's own key hits its
quota, that is not our outage, and the message must say so. `LLMError.blame`
carries that distinction to the UI instead of collapsing everything into a 500.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Blame(str, Enum):
    """Who has to act. Drives the message the user sees."""

    USER_KEY = "user_key"
    """Their key: missing, invalid, out of quota, or lacking model access."""
    PROVIDER = "provider"
    """Gemini is down or rate-limiting globally. Retry later."""
    OURS = "ours"
    """Our bug: a bad prompt, a bad schema, an unparseable response."""
    CONTENT = "content"
    """The request was refused on content grounds. Neither side is broken."""


class LLMError(Exception):
    """Base for every LLM failure. Never leaks the API key into its message."""

    blame: Blame = Blame.OURS
    retryable: bool = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def user_message(self) -> str:
        return self.message


class LLMAuthError(LLMError):
    """No key, wrong key, or a key without access to the requested model."""

    blame = Blame.USER_KEY


class LLMQuotaError(LLMError):
    """The key is out of quota or being rate-limited.

    Retryable, but on the user's key retrying aggressively just burns their
    rate limit — so the caller backs off rather than hammering.
    """

    blame = Blame.USER_KEY
    retryable = True


class LLMProviderError(LLMError):
    """A 5xx or a timeout. Not our fault and not the user's."""

    blame = Blame.PROVIDER
    retryable = True


class LLMBlockedError(LLMError):
    """The provider's safety filter refused the request or the response.

    Real for résumés: defense, medical, and security work all trip filters that
    were not written with job applications in mind. This must surface as a clean
    abstention the user can act on, never as a 500 and never as a silent empty
    answer that looks like a model refusal to help.
    """

    blame = Blame.CONTENT


class LLMSchemaError(LLMError):
    """The response did not validate against the requested schema.

    Deliberately NOT retryable. A schema mismatch means our schema or prompt is
    wrong, and retrying spends the user's money to get the same failure. It also
    must never be swallowed: unvalidated structuring output reaching L2 is the
    exact contamination the confirmation pass exists to prevent.
    """

    blame = Blame.OURS


@dataclass(frozen=True)
class LLMUsage:
    """Token accounting. On BYOK this is the user's bill, so it is not optional."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    """Tokens served from the provider's cache. Our prompts are small enough that
    only *implicit* caching applies — explicit context caching has a token
    minimum we do not reach. Reported as-is rather than claimed as a saving."""
    thinking_tokens: int = 0
    """Billed as output but invisible in the response. Worth showing precisely
    because it is otherwise an unexplained charge."""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
        )


@dataclass
class LLMResponse(Generic[T]):
    """What a call returns. `parsed` is None only when no schema was requested."""

    text: str
    parsed: T | None
    usage: LLMUsage
    model: str
    finish_reason: str | None = None
    ms: int = 0
    attempts: int = 1
    truncated: bool = False
    """Hit `max_output_tokens`. The text is a fragment — callers must not treat a
    truncated answer as a complete one."""


@dataclass
class LLMCall:
    """One request. A dataclass rather than a long signature because the pipeline
    builds these up in stages and needs to log the exact call it made."""

    prompt: str
    system: str | None = None
    model: str | None = None
    """None means "the fast tier". Resolved by the client from settings."""
    schema: type[BaseModel] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    thinking_budget: int | None = None
    stop_sequences: list[str] = field(default_factory=list)
    label: str = ""
    """For traces: "structure", "tag", "generate". Not sent to the provider."""


class LLMClient(Protocol):
    """Implemented by `GeminiClient`, and by `FakeClient` in tests.

    A Protocol rather than a base class so tests can supply a stub without
    inheriting a constructor that wants an API key.
    """

    def generate(self, call: LLMCall) -> LLMResponse: ...

    def list_models(self) -> list[str]:
        """Verify what this key can actually reach, instead of trusting a
        hardcoded model name that may have been retired."""
        ...


class Timer:
    """Wall-clock for the trace. Every stage in this codebase reports ms."""

    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)


__all__ = [
    "Blame",
    "LLMError",
    "LLMAuthError",
    "LLMQuotaError",
    "LLMProviderError",
    "LLMBlockedError",
    "LLMSchemaError",
    "LLMUsage",
    "LLMResponse",
    "LLMCall",
    "LLMClient",
    "Timer",
]
