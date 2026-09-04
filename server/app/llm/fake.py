"""A scripted `LLMClient` for tests and for offline development.

Not a mock library shim: the point is that every test of structuring, tagging,
and generation can assert on **the exact prompt we sent**. Most of the risk in
those steps is prompt construction — a missing JD fence, evidence that never made
it into the prompt, a closed list that wasn't actually closed — and a fake that
records calls catches those, while a network call would hide them behind
whatever the model happened to answer.

It also means the test suite stays hermetic and free. 249 tests that each cost a
Gemini call is a test suite nobody runs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel

from .base import LLMCall, LLMError, LLMResponse, LLMUsage

#: Cheap stand-in for real accounting, so callers that surface token counts have
#: something non-zero to show. Not meant to resemble Gemini's tokenizer.
def _estimate_usage(call: LLMCall, text: str) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=len(call.prompt) // 4 + (len(call.system or "") // 4),
        output_tokens=max(1, len(text) // 4),
    )


class FakeClient:
    """Returns scripted responses in order, and records what it was asked.

    Scripts may contain:
      * a `BaseModel`   — returned as `parsed`
      * a `str`         — returned as `text`
      * an `LLMError`   — raised, for testing failure paths
      * an `LLMResponse` — returned verbatim, for the cases where the envelope is
                          the thing under test (truncation, finish_reason, usage)
      * a callable      — `fn(call) -> any of the above`, for responses that must
                          depend on the prompt
    """

    def __init__(
        self,
        script: Iterable[
            BaseModel | str | LLMError | LLMResponse | Callable[[LLMCall], object]
        ] = (),
        *,
        model: str = "fake-model",
        models: list[str] | None = None,
    ) -> None:
        self._script = list(script)
        self._model = model
        self._models = models if models is not None else [model]
        self.calls: list[LLMCall] = []

    # ── LLMClient ──────────────────────────────────────────────────────────────

    def generate(self, call: LLMCall) -> LLMResponse:
        self.calls.append(call)

        if not self._script:
            raise AssertionError(
                f"FakeClient ran out of scripted responses on call "
                f"{len(self.calls)} (label={call.label!r}). Add one, or the test "
                f"is exercising a path it did not intend to."
            )

        item = self._script.pop(0)
        if callable(item) and not isinstance(item, BaseModel):
            item = item(call)  # type: ignore[operator]

        if isinstance(item, LLMError):
            raise item

        if isinstance(item, LLMResponse):
            return item

        if isinstance(item, BaseModel):
            text = item.model_dump_json()
            if call.schema is not None and not isinstance(item, call.schema):
                raise AssertionError(
                    f"scripted {type(item).__name__} does not match the requested "
                    f"schema {call.schema.__name__} — the test and the code disagree"
                )
            return LLMResponse(
                text=text,
                parsed=item,
                usage=_estimate_usage(call, text),
                model=self._model,
                finish_reason="STOP",
            )

        text = str(item)
        return LLMResponse(
            text=text,
            parsed=None,
            usage=_estimate_usage(call, text),
            model=self._model,
            finish_reason="STOP",
        )

    def list_models(self) -> list[str]:
        return list(self._models)

    # ── assertions ─────────────────────────────────────────────────────────────

    @property
    def last(self) -> LLMCall:
        assert self.calls, "no LLM call was made"
        return self.calls[-1]

    @property
    def exhausted(self) -> bool:
        """False means the code made fewer calls than the test expected — usually
        an early return that skipped a stage."""
        return not self._script

    def prompts(self) -> list[str]:
        return [c.prompt for c in self.calls]

    def labels(self) -> list[str]:
        return [c.label for c in self.calls]


__all__ = ["FakeClient"]
