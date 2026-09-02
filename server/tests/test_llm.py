"""LLM seam tests. Hermetic: real SDK error objects and a scripted `client.models`
stand in for the network, which is the only way to cover the paths that actually
matter (quota, safety block, truncation, retry) deterministically — you cannot ask
Gemini to please rate-limit you on demand.

Key resolution gets disproportionate attention for a one-user tool because the
current setup (a key in `.env`) and the eventual one (a key per request) differ
only in which branch of `resolve_key` fires, and keeping that true is cheap only
while it is already true.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm import keys as keys_mod
from app.llm.base import (
    Blame,
    LLMAuthError,
    LLMBlockedError,
    LLMCall,
    LLMProviderError,
    LLMQuotaError,
    LLMSchemaError,
    LLMUsage,
)
from app.llm.fake import FakeClient
from app.llm.gemini import GeminiClient, _usage_of

GOOD_KEY = "AIzaSyDUMMY_KEY_FOR_TESTS_0000000000000"


class Extracted(BaseModel):
    employer: str
    title: str


@pytest.fixture
def settings(monkeypatch):
    """A fresh Settings per test — `get_settings` is lru_cached in production."""

    def _apply(**kw):
        s = Settings(_env_file=None, **kw)
        monkeypatch.setattr("app.config.get_settings", lambda: s)
        monkeypatch.setattr("app.llm.keys.get_settings", lambda: s)
        monkeypatch.setattr("app.llm.gemini.get_settings", lambda: s)
        return s

    return _apply


# ── BYOK key resolution ────────────────────────────────────────────────────────


def test_request_key_wins_over_server_key(settings):
    settings(gemini_api_key="AIzaSERVER_KEY_0000000000000000000000")
    assert keys_mod.resolve_key(GOOD_KEY) == GOOD_KEY


def test_server_key_is_the_dev_fallback(settings):
    settings(gemini_api_key=GOOD_KEY)
    assert keys_mod.resolve_key(None) == GOOD_KEY


def test_require_user_key_disables_the_fallback(settings):
    """Production setting. A misconfigured deploy must fail loudly rather than
    quietly billing us for every user's calls."""
    settings(gemini_api_key=GOOD_KEY, require_user_key=True)
    with pytest.raises(LLMAuthError, match="your own"):
        keys_mod.resolve_key(None)
    # ...but an explicit user key still works.
    assert keys_mod.resolve_key(GOOD_KEY) == GOOD_KEY


def test_no_key_anywhere_explains_what_to_do(settings):
    settings(gemini_api_key=None)
    with pytest.raises(LLMAuthError) as exc:
        keys_mod.resolve_key(None)
    assert "GEMINI_API_KEY" in str(exc.value)


def test_blank_request_key_falls_through(settings):
    """An empty string from a form field is "not supplied", not "supplied empty"."""
    settings(gemini_api_key=GOOD_KEY)
    assert keys_mod.resolve_key("   ") == GOOD_KEY


@pytest.mark.parametrize(
    "bad, hint",
    [
        ("short", "single line"),
        ("AIza with spaces in it 000000000000000", "single line"),
        ("sk-proj-abcdefghijklmnopqrstuvwxyz", "OpenAI"),
    ],
)
def test_obvious_paste_accidents_get_a_useful_error(settings, bad, hint):
    settings()
    with pytest.raises(LLMAuthError, match=hint):
        keys_mod.resolve_key(bad)


def test_has_server_key_never_returns_the_key(settings):
    settings(gemini_api_key=GOOD_KEY)
    assert keys_mod.has_server_key() is True
    settings(gemini_api_key=GOOD_KEY, require_user_key=True)
    assert keys_mod.has_server_key() is False, "production must not advertise a fallback"


def test_redact_keeps_only_the_tail():
    assert keys_mod.redact(GOOD_KEY) == f"…{GOOD_KEY[-4:]}"
    assert GOOD_KEY[:10] not in keys_mod.redact(GOOD_KEY)
    assert keys_mod.redact(None) == "(none)"


def test_client_construction_rejects_a_bad_key_immediately(settings):
    """Fail here, not three pipeline stages later with a confusing message."""
    settings()
    with pytest.raises(LLMAuthError):
        GeminiClient("nope")


def test_clients_are_not_cached_by_key(settings):
    """Caching by key would hold users' keys in a process-global dict for the
    server's lifetime — the one thing BYOK promises not to do."""
    from app.llm.gemini import get_client

    settings()
    assert get_client(GOOD_KEY) is not get_client(GOOD_KEY)


# ── error mapping: BYOK blame has to land on the right party ───────────────────


def api_error(code: int, message: str = "boom", status: str = "ERROR") -> Exception:
    """A real SDK error, built the way the SDK builds them from a failed response.

    Constructing the genuine class rather than a stand-in means these tests
    actually pin the `ClientError`/`ServerError` hierarchy `_map_error` branches
    on, so an SDK reshuffle fails here instead of in production.
    """
    from google.genai import errors as ge

    cls = ge.ServerError if code >= 500 else ge.ClientError
    return cls(code, {"error": {"code": code, "message": message, "status": status}})


@pytest.mark.parametrize(
    "code, expected, blame",
    [
        (401, LLMAuthError, Blame.USER_KEY),
        (403, LLMAuthError, Blame.USER_KEY),
        (404, LLMAuthError, Blame.USER_KEY),
        (429, LLMQuotaError, Blame.USER_KEY),
        (400, LLMSchemaError, Blame.OURS),
        (500, LLMProviderError, Blame.PROVIDER),
        (503, LLMProviderError, Blame.PROVIDER),
    ],
)
def test_status_codes_map_to_the_right_blame(code, expected, blame):
    mapped = GeminiClient._map_error(api_error(code))
    assert isinstance(mapped, expected)
    assert mapped.blame is blame


def test_quota_is_the_users_problem_not_an_outage():
    """The message must not read like our server broke — it did not."""
    mapped = GeminiClient._map_error(api_error(429, status="RESOURCE_EXHAUSTED"))
    assert mapped.blame is Blame.USER_KEY
    assert mapped.retryable is True
    assert "quota" in mapped.user_message().lower()


def test_a_bad_request_is_our_bug_not_the_users():
    mapped = GeminiClient._map_error(api_error(400, status="INVALID_ARGUMENT"))
    assert "our side" in mapped.user_message()


def test_an_invalid_key_is_not_reported_as_our_bug():
    """Google returns an invalid API key as 400 INVALID_ARGUMENT, *not* 401 —
    captured from the live API, not guessed. Blaming ourselves for every 400 sent
    a user who mistyped their key looking in entirely the wrong place.
    """
    from google.genai import errors as ge

    real = ge.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                        "domain": "googleapis.com",
                    }
                ],
            }
        },
    )
    mapped = GeminiClient._map_error(real)
    assert isinstance(mapped, LLMAuthError)
    assert mapped.blame is Blame.USER_KEY
    assert "aistudio.google.com/apikey" in mapped.user_message()


def test_invalid_key_is_caught_even_without_the_reason_code():
    """Belt and braces: if the details payload ever changes shape, the prose match
    still keeps the blame on the key rather than on us."""
    mapped = GeminiClient._map_error(
        api_error(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT")
    )
    assert isinstance(mapped, LLMAuthError)


def test_errors_never_leak_the_key():
    mapped = GeminiClient._map_error(api_error(401, f"key {GOOD_KEY} rejected"))
    # The provider echoed the key back; it may live in `detail` for our logs, but
    # the user-facing message must not carry it.
    assert GOOD_KEY not in mapped.user_message()


def test_already_mapped_errors_pass_through_unchanged():
    """`generate()` maps inside the retry loop; double-mapping a quota error into
    a provider error would blame the wrong party on attempt two."""
    original = LLMQuotaError("out of quota")
    assert GeminiClient._map_error(original) is original


def test_a_timeout_is_the_providers_problem_not_the_key():
    class ReadTimeout(Exception):
        pass

    mapped = GeminiClient._map_error(ReadTimeout("timed out"))
    assert isinstance(mapped, LLMProviderError)
    assert mapped.retryable is True


def test_schema_errors_are_not_retryable():
    """Retrying a schema mismatch spends the user's money for the same failure."""
    assert LLMSchemaError("x").retryable is False
    assert LLMAuthError("x").retryable is False
    assert LLMQuotaError("x").retryable is True
    assert LLMProviderError("x").retryable is True


# ── retries ────────────────────────────────────────────────────────────────────


class _Models:
    """Stands in for `client.models`, raising a scripted sequence."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def stub_sdk(monkeypatch, settings):
    """Wire a scripted `client.models` into a real GeminiClient, no network."""
    monkeypatch.setattr("time.sleep", lambda _s: None)  # keep the suite fast

    def _build(script, **kw):
        settings(**kw)
        client = GeminiClient(GOOD_KEY)
        models = _Models(script)
        client._client = type("C", (), {"models": models})()
        # `_build_config` needs the real SDK types module, which is installed.
        return client, models

    return _build


def test_a_transient_failure_is_actually_retried(stub_sdk):
    """The retry loop caught our own exception types, but the SDK raises its own —
    so the mapping has to happen before the retry decision, or max_retries is dead
    configuration."""
    client, models = stub_sdk([api_error(503), _Raw(text="second try")], llm_max_retries=2)
    res = client.generate(LLMCall(prompt="p"))
    assert res.text == "second try"
    assert models.calls == 2
    assert res.attempts == 2


def test_retries_are_bounded(stub_sdk):
    client, models = stub_sdk([api_error(503)] * 5, llm_max_retries=2)
    with pytest.raises(LLMProviderError):
        client.generate(LLMCall(prompt="p"))
    assert models.calls == 3, "one initial attempt plus two retries"


def test_a_rejected_key_is_not_retried(stub_sdk):
    """Retrying a bad key cannot help, and on BYOK each attempt is the user's
    money."""
    client, models = stub_sdk([api_error(401)] * 3, llm_max_retries=2)
    with pytest.raises(LLMAuthError):
        client.generate(LLMCall(prompt="p"))
    assert models.calls == 1


def test_a_safety_block_is_not_retried(stub_sdk):
    client, models = stub_sdk([_Raw(block="SAFETY", candidates=[])] * 3, llm_max_retries=2)
    with pytest.raises(LLMBlockedError):
        client.generate(LLMCall(prompt="p"))
    assert models.calls == 1


def test_a_schema_mismatch_is_not_retried(stub_sdk):
    client, models = stub_sdk([_Raw(text='{"employer": "Acme"}')] * 3, llm_max_retries=2)
    with pytest.raises(LLMSchemaError):
        client.generate(LLMCall(prompt="p", schema=Extracted))
    assert models.calls == 1


def test_quota_is_retried_since_a_rate_limit_clears(stub_sdk):
    client, models = stub_sdk(
        [api_error(429), _Raw(text="ok", parsed=Extracted(employer="A", title="B"))],
        llm_max_retries=2,
    )
    res = client.generate(LLMCall(prompt="p", schema=Extracted))
    assert res.parsed.employer == "A"
    assert models.calls == 2


def test_truncation_is_reported_on_the_response(stub_sdk):
    """Without a schema there is nothing to fail validation, so the fragment comes
    back — and callers must be able to see that it is a fragment."""
    client, _ = stub_sdk([_Raw(text="Dear hiring mana", candidates=[_Candidate("MAX_TOKENS")])])
    res = client.generate(LLMCall(prompt="p"))
    assert res.truncated is True
    assert res.finish_reason == "MAX_TOKENS"


def test_usage_reaches_the_response(stub_sdk):
    usage = type("U", (), {"prompt_token_count": 40, "candidates_token_count": 9})()
    client, _ = stub_sdk([_Raw(text="hi", usage=usage)])
    res = client.generate(LLMCall(prompt="p"))
    assert res.usage.total_tokens == 49
    assert res.ms >= 0


# ── safety and truncation: the silent ones ─────────────────────────────────────


class _Enum:
    def __init__(self, name: str) -> None:
        self.name = name


class _Candidate:
    def __init__(self, finish: str | None) -> None:
        self.finish_reason = _Enum(finish) if finish else None


class _Feedback:
    def __init__(self, block: str) -> None:
        self.block_reason = _Enum(block)


class _Raw:
    """Minimal stand-in for the SDK response object.

    The client reads it entirely through `getattr` defaults, which is what makes a
    stub like this legitimate here — and is itself deliberate, since a response
    field the SDK stops populating must not crash a form fill.
    """

    def __init__(self, *, text="", candidates=None, block=None, parsed=None, usage=None):
        self.text = text
        self.candidates = candidates if candidates is not None else [_Candidate("STOP")]
        self.prompt_feedback = _Feedback(block) if block else None
        self.parsed = parsed
        self.usage_metadata = usage


def test_prompt_safety_block_is_explained_not_swallowed():
    """A refusal returns no candidate; naive code reads `.text` and gets "".

    That empty string would be stored as a real answer.
    """
    with pytest.raises(LLMBlockedError) as exc:
        GeminiClient._check_blocked(_Raw(block="SAFETY", candidates=[]))
    assert exc.value.blame is Blame.CONTENT
    assert "defense" in exc.value.user_message()


@pytest.mark.parametrize("reason", ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"])
def test_response_safety_block_is_caught(reason):
    with pytest.raises(LLMBlockedError):
        GeminiClient._check_blocked(_Raw(candidates=[_Candidate(reason)]))


def test_recitation_gets_its_own_message():
    with pytest.raises(LLMBlockedError, match="reproducing source text"):
        GeminiClient._check_blocked(_Raw(candidates=[_Candidate("RECITATION")]))


def test_no_candidates_at_all_is_an_error():
    with pytest.raises(LLMBlockedError):
        GeminiClient._check_blocked(_Raw(candidates=[]))


def test_a_normal_response_passes_the_block_check():
    GeminiClient._check_blocked(_Raw(text="fine", candidates=[_Candidate("STOP")]))


def test_truncated_schema_response_fails_closed(settings):
    """MAX_TOKENS returns partial JSON and no exception. Half a record must not
    reach L2 — and the message must say what to do."""
    settings()
    client = GeminiClient(GOOD_KEY)
    raw = _Raw(text='{"employer": "Acme Cor', candidates=[_Candidate("MAX_TOKENS")])
    with pytest.raises(LLMSchemaError, match="cut off"):
        client._parse(raw, raw.text, Extracted, truncated=True)


def test_wrong_shape_fails_closed_with_a_reason(settings):
    settings()
    client = GeminiClient(GOOD_KEY)
    raw = _Raw(text='{"employer": "Acme"}')  # missing `title`
    with pytest.raises(LLMSchemaError) as exc:
        client._parse(raw, raw.text, Extracted, truncated=False)
    assert "nothing" in exc.value.user_message().lower()
    assert "title" in (exc.value.detail or ""), "the detail should name the bad field"


def test_parse_prefers_the_sdks_validated_object(settings):
    settings()
    client = GeminiClient(GOOD_KEY)
    want = Extracted(employer="Acme", title="Engineer")
    raw = _Raw(text="{}", parsed=want)
    assert client._parse(raw, raw.text, Extracted, truncated=False) is want


def test_parse_recovers_when_the_sdk_leaves_parsed_none(settings):
    settings()
    client = GeminiClient(GOOD_KEY)
    raw = _Raw(text='{"employer": "Acme", "title": "Engineer"}', parsed=None)
    got = client._parse(raw, raw.text, Extracted, truncated=False)
    assert got.employer == "Acme"


def test_empty_response_fails_closed(settings):
    settings()
    client = GeminiClient(GOOD_KEY)
    with pytest.raises(LLMSchemaError):
        client._parse(_Raw(text=""), "", Extracted, truncated=False)


# ── usage accounting: the user is paying ───────────────────────────────────────


def test_usage_reads_all_four_counters():
    usage = _usage_of(
        _Raw(
            usage=type(
                "U",
                (),
                {
                    "prompt_token_count": 1200,
                    "candidates_token_count": 300,
                    "cached_content_token_count": 800,
                    "thoughts_token_count": 150,
                },
            )()
        )
    )
    assert usage.prompt_tokens == 1200
    assert usage.output_tokens == 300
    assert usage.cached_tokens == 800
    # Thinking tokens are billed but invisible in the response — showing them is
    # the difference between a bill the user understands and one they don't.
    assert usage.thinking_tokens == 150
    assert usage.total_tokens == 1500


def test_missing_usage_block_does_not_crash_a_fill():
    assert _usage_of(_Raw(usage=None)) == LLMUsage()


def test_usage_adds_up_across_calls():
    a = LLMUsage(prompt_tokens=10, output_tokens=5, thinking_tokens=2)
    b = LLMUsage(prompt_tokens=20, output_tokens=7, cached_tokens=3)
    total = a + b
    assert (total.prompt_tokens, total.output_tokens) == (30, 12)
    assert (total.cached_tokens, total.thinking_tokens) == (3, 2)


# ── request construction ───────────────────────────────────────────────────────


def test_schema_calls_request_json_and_disable_thinking(settings):
    """Structuring and tagging are extraction. Thinking tokens there are billed
    output the user never sees."""
    settings(thinking_budget_fast=0)
    client = GeminiClient(GOOD_KEY)
    config = client._build_config(LLMCall(prompt="x", schema=Extracted))
    assert config.response_mime_type == "application/json"
    assert config.response_schema is Extracted
    assert config.thinking_config.thinking_budget == 0


def test_prose_calls_leave_thinking_alone(settings):
    """Generation is the one place reasoning may be worth paying for, so we do
    not silently disable it."""
    settings()
    client = GeminiClient(GOOD_KEY)
    config = client._build_config(LLMCall(prompt="write something"))
    assert config.response_mime_type is None
    assert config.thinking_config is None


def test_explicit_thinking_budget_overrides_the_default(settings):
    settings(thinking_budget_fast=0)
    client = GeminiClient(GOOD_KEY)
    config = client._build_config(LLMCall(prompt="x", schema=Extracted, thinking_budget=512))
    assert config.thinking_config.thinking_budget == 512


def test_output_ceiling_is_always_set(settings):
    """The user is paying, so a runaway response is their money."""
    settings(llm_max_output_tokens=777)
    client = GeminiClient(GOOD_KEY)
    assert client._build_config(LLMCall(prompt="x")).max_output_tokens == 777
    assert (
        client._build_config(LLMCall(prompt="x", max_output_tokens=99)).max_output_tokens == 99
    )


def test_model_defaults_to_the_fast_tier(settings):
    s = settings(llm_model_fast="gemini-2.5-flash")
    assert LLMCall(prompt="x").model is None
    assert s.llm_model_fast == "gemini-2.5-flash"


# ── the fake client ────────────────────────────────────────────────────────────


def test_fake_returns_scripted_parsed_objects():
    want = Extracted(employer="Acme", title="Engineer")
    fake = FakeClient([want])
    res = fake.generate(LLMCall(prompt="p", schema=Extracted, label="structure"))
    assert res.parsed is want
    assert fake.labels() == ["structure"]
    assert fake.exhausted


def test_fake_records_the_prompt_we_actually_sent():
    """Most of the risk in steps 3/5/6 is prompt construction, so tests assert on
    the prompt rather than on a model's reply."""
    fake = FakeClient(["ok"])
    fake.generate(LLMCall(prompt="QUESTION: why us?", system="be terse"))
    assert "why us?" in fake.last.prompt
    assert fake.last.system == "be terse"


def test_fake_can_raise_to_exercise_failure_paths():
    fake = FakeClient([LLMQuotaError("out of quota")])
    with pytest.raises(LLMQuotaError):
        fake.generate(LLMCall(prompt="p"))


def test_fake_responses_may_depend_on_the_prompt():
    fake = FakeClient([lambda call: f"saw {len(call.prompt)} chars"])
    assert fake.generate(LLMCall(prompt="12345")).text == "saw 5 chars"


def test_fake_rejects_a_script_that_disagrees_with_the_schema():
    class Other(BaseModel):
        x: int

    fake = FakeClient([Other(x=1)])
    with pytest.raises(AssertionError, match="does not match the requested schema"):
        fake.generate(LLMCall(prompt="p", schema=Extracted))


def test_fake_complains_when_the_code_calls_more_than_expected():
    fake = FakeClient([])
    with pytest.raises(AssertionError, match="ran out of scripted responses"):
        fake.generate(LLMCall(prompt="p", label="tag"))


# ── HTTP surface ───────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_meta_llm_reports_config_without_calling_out(client):
    """No `api_key` query param means no provider call, so this endpoint is free
    and works offline — the viewer polls it on mount."""
    body = client.get("/meta/llm").json()
    assert body["provider"] == "gemini"
    assert body["model_fast"].startswith("gemini")
    assert isinstance(body["has_server_key"], bool)
    assert body["models"] is None and body["error"] is None


def test_meta_llm_never_returns_a_key(client):
    """Whatever is in .env, the response must not carry it — not even a fragment."""
    from app.config import get_settings

    configured = (get_settings().gemini_api_key or "").strip()
    raw = client.get("/meta/llm").text
    assert "api_key" not in raw and "gemini_api_key" not in raw
    if configured:
        assert configured not in raw
        assert configured[-4:] not in raw, "not even the last four"


def test_meta_llm_reports_a_rejected_key_as_a_200_with_blame(client):
    """A 4xx here would make the viewer show a generic failure; the caller wants
    the reason next to the rest of the config."""
    res = client.get("/meta/llm", params={"api_key": "sk-wrong-provider-000000000000"})
    assert res.status_code == 200
    assert res.json()["error"]["blame"] == "user_key"
    assert "Gemini" in res.json()["error"]["message"]
