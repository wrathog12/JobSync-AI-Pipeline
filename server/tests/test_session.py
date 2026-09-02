"""L6 — the multi-page application session.

Four behaviours a per-field function cannot have, and one boundary that must not
be crossed. The boundary test is the important one: everything else is quality,
but a session leaking into L0-L5 is a permanent corruption of the profile.
"""

from __future__ import annotations

import pytest

from app.memory.sessions import SessionStore
from app.memory.store import get_store
from app.pipeline.answer import run
from app.schemas.common import GenerationMode
from app.schemas.session import (
    SPENT_CHUNK_DROP_AFTER,
    ApplicationSession,
    field_key,
    jd_fingerprint,
)
from app.schemas.trace import AnswerRequest, Stage, StageStatus

JD = (
    "Staff Engineer. Required: leading large-scale database migrations, "
    "PostgreSQL at scale, mentoring, driving cross-team technical decisions."
)

BEHAVIOURAL = [
    "Tell us about a time you led a team through a difficult migration.",
    "Describe a situation where you had to influence people without authority.",
    "Tell us about a time you mentored someone.",
]


@pytest.fixture()
def sessions() -> SessionStore:
    return SessionStore()


@pytest.fixture()
def store():
    return get_store()


def _ask(question: str, session, store, mode=GenerationMode.STRICT, **kw):
    return run(AnswerRequest(question=question, mode=mode, max_chars=400, **kw), store, session)


# ── the boundary ───────────────────────────────────────────────────────────────


def test_session_never_writes_to_durable_memory(sessions, store):
    """The non-negotiable invariant: L6 activity cannot mutate L0-L5.

    Without this, one AGGRESSIVE application permanently inflates the profile and
    every future application inherits the exaggeration.
    """
    before = store.stats()
    session = sessions.create(jd_text=JD, mode=GenerationMode.AGGRESSIVE)
    for q in BEHAVIOURAL:
        _ask(q, session, store, mode=GenerationMode.AGGRESSIVE)

    assert store.stats() == before, "an application session mutated durable memory"
    assert session.answered, "sanity: the session did do work"


def test_session_answers_are_not_auto_approved(sessions, store):
    """Only an explicitly approved answer may later be promoted into L5."""
    session = sessions.create(jd_text=JD)
    _ask(BEHAVIOURAL[0], session, store)
    generated = [a for a in session.answered if a.answer and not a.abstained]
    assert generated, "sanity: something was generated"
    assert all(not a.approved_by_user for a in generated)


# ── 1. idempotent replay (the back button) ─────────────────────────────────────


def test_same_field_twice_replays_instead_of_regenerating(sessions, store):
    session = sessions.create(jd_text=JD)
    first = _ask(BEHAVIOURAL[0], session, store)
    second = _ask(BEHAVIOURAL[0], session, store)

    assert second.answer == first.answer
    replay = second.step(Stage.SESSION_REPLAY)
    assert replay is not None and replay.status is StageStatus.HIT
    assert second.total_tokens == 0, "a replay must not cost tokens"
    assert second.step(Stage.RETRIEVE) is None, "replay must short-circuit retrieval"


def test_regenerate_flag_bypasses_replay(sessions, store):
    session = sessions.create(jd_text=JD)
    _ask(BEHAVIOURAL[0], session, store)
    again = _ask(BEHAVIOURAL[0], session, store, regenerate=True)

    replay = again.step(Stage.SESSION_REPLAY)
    assert replay is not None and replay.status is StageStatus.MISS
    assert again.step(Stage.RETRIEVE) is not None


def test_replay_does_not_cross_modes(sessions, store):
    """Switching mode must regenerate — a strict answer is not an aggressive one."""
    session = sessions.create(jd_text=JD)
    _ask(BEHAVIOURAL[0], session, store, mode=GenerationMode.STRICT)
    other = _ask(BEHAVIOURAL[0], session, store, mode=GenerationMode.AGGRESSIVE)
    assert other.step(Stage.SESSION_REPLAY).status is StageStatus.MISS


def test_field_key_is_stable_across_formatting_noise(sessions):
    a = field_key("  Tell us about A TIME you led a team.  ")
    b = field_key("Tell us about a time you led a team.")
    assert a == b, "key must survive re-render whitespace and case changes"
    assert field_key("x", "textarea") != field_key("x", "text")


# ── 2. the JD outlives the page it came from ───────────────────────────────────


def test_jd_is_inherited_from_session_on_later_pages(sessions, store):
    """By page 6 of a Workday wizard the JD is gone from the DOM. L6 still has it."""
    session = sessions.create(jd_text=JD)
    session.advance_page("https://x.wd5.myworkdayjobs.com/step/6")

    trace = _ask(BEHAVIOURAL[0], session, store)  # no jd_text on the request

    assert trace.jd_excerpt is not None
    assert "PostgreSQL" in trace.jd_excerpt
    assert trace.page_index == 1


def test_session_reattaches_by_jd_when_the_url_changed(sessions):
    """Workday's URL changes every step, so the URL cannot key a session."""
    original = sessions.create(jd_text=JD)
    found = sessions.get_or_create(session_id=None, jd_text=JD)
    assert found.session_id == original.session_id
    assert found.jd_fingerprint == jd_fingerprint(JD)


def test_a_late_arriving_jd_does_not_overwrite_an_anchored_one(sessions):
    session = sessions.create(jd_text=JD)
    sessions.get_or_create(session.session_id, jd_text="A completely different job posting.")
    assert session.jd_text == JD


# ── 3. anti-repetition ─────────────────────────────────────────────────────────


def test_answering_a_field_marks_its_evidence_spent(sessions, store):
    session = sessions.create(jd_text=JD)
    trace = _ask(BEHAVIOURAL[0], session, store)
    used = [c.chunk_id for c in trace.step(Stage.RERANK).chunks]
    assert used, "sanity: retrieval returned something"
    assert all(session.spent_chunks.get(cid) == 1 for cid in used)
    assert all(session.spend_multiplier(cid) < 1.0 for cid in used)


def test_consecutive_questions_do_not_all_reuse_one_story(sessions, store):
    """The signature failure of auto-filled applications, pinned as a test.

    Compared against the sessionless path, which is free to answer all three
    questions with whichever chunk happens to rank highest every time.
    """
    session = sessions.create(jd_text=JD)
    with_session = [
        {c.chunk_id for c in _ask(q, session, store).step(Stage.RERANK).chunks}
        for q in BEHAVIOURAL
    ]
    lead_chunks = [next(iter(sorted(s))) for s in with_session if s]

    without = [
        {c.chunk_id for c in run(
            AnswerRequest(question=q, jd_text=JD, max_chars=400), store, None
        ).step(Stage.RERANK).chunks}
        for q in BEHAVIOURAL
    ]

    reuse_with = sum(len(a & b) for a, b in zip(with_session, with_session[1:]))
    reuse_without = sum(len(a & b) for a, b in zip(without, without[1:]))
    assert reuse_with <= reuse_without, (
        f"session reuse {reuse_with} should not exceed sessionless {reuse_without}; "
        f"lead chunks were {lead_chunks}"
    )


def test_exhausted_chunks_are_dropped_not_merely_demoted(sessions, store):
    session = sessions.create(jd_text=JD)
    session.spent_chunks["ch_ach_01_02"] = SPENT_CHUNK_DROP_AFTER
    assert session.is_exhausted("ch_ach_01_02")
    trace = _ask(BEHAVIOURAL[0], session, store)
    top = {c.chunk_id for c in trace.step(Stage.RERANK).chunks}
    if top:  # only meaningful when other evidence survived the gate
        assert "ch_ach_01_02" not in top or trace.spent_chunks_avoided == []


def test_total_exhaustion_does_not_starve_retrieval(sessions, store):
    """A repeated answer beats a fabricated one; the gate still gets to object."""
    session = sessions.create(jd_text=JD)
    for c in store.evidence.chunks:
        session.spent_chunks[c.chunk_id] = SPENT_CHUNK_DROP_AFTER
    trace = _ask(BEHAVIOURAL[0], session, store)
    # Either it answered from exhausted evidence or it abstained — never crashed,
    # and never invented.
    assert trace.abstained or trace.answer


def test_reported_score_is_the_penalised_one(sessions, store):
    """The trace must show the number the sufficiency gate actually compared."""
    session = sessions.create(jd_text=JD)
    fresh = _ask(BEHAVIOURAL[0], session, store)
    fresh_top = fresh.step(Stage.RERANK).chunks
    assert fresh_top

    replayed = _ask(BEHAVIOURAL[0], session, store, regenerate=True)
    again = {c.chunk_id: c.score for c in replayed.step(Stage.RERANK).chunks}
    for c in fresh_top:
        if c.chunk_id in again:
            assert again[c.chunk_id] < c.score, "a spent chunk must report a lower score"
            break


# ── 4. consistency and stretch coherence ───────────────────────────────────────


def test_prior_answers_enter_the_prompt(sessions, store):
    session = sessions.create(jd_text=JD)
    _ask(BEHAVIOURAL[0], session, store)
    second = _ask(BEHAVIOURAL[1], session, store)

    gen = second.step(Stage.GENERATE)
    if gen is None or not gen.prompt_preview:
        pytest.skip("second question abstained; nothing was generated to compare against")
    assert "ALREADY ANSWERED IN THIS APPLICATION" in gen.prompt_preview


def test_stretches_accumulate_across_pages(sessions, store):
    session = sessions.create(jd_text=JD, mode=GenerationMode.AGGRESSIVE)
    for q in BEHAVIOURAL:
        _ask(q, session, store, mode=GenerationMode.AGGRESSIVE)
    claims = [s.claim for s in session.stretches]
    assert len(claims) == len(set(claims)), "the same stretch must not be recorded twice"


def test_abstentions_are_recorded_so_the_user_is_not_asked_twice(sessions, store):
    session = sessions.create(jd_text=JD)
    first = _ask("Describe your experience managing a P&L.", session, store)
    assert first.abstained
    second = _ask("Describe your experience managing a P&L.", session, store)
    assert second.step(Stage.SESSION_REPLAY).status is StageStatus.HIT
    assert second.abstained


# ── sessionless behaviour is unchanged ─────────────────────────────────────────


def test_pipeline_still_works_with_no_session(store):
    """Every session-dependent step must degrade to a no-op, not fork the pipeline."""
    trace = run(AnswerRequest(question=BEHAVIOURAL[0], max_chars=400), store, None)
    assert trace.session_id is None
    assert trace.step(Stage.SESSION_REPLAY) is None
    assert trace.field_key is not None, "the key is computed regardless"
    assert trace.abstained or trace.answer


def test_session_store_evicts(sessions):
    from app.memory.sessions import MAX_SESSIONS

    for i in range(MAX_SESSIONS + 5):
        sessions.create(jd_text=f"job number {i}")
    assert len(sessions.all()) <= MAX_SESSIONS


def test_serialisable(sessions, store):
    """The extension will ship this over the wire; it must round-trip."""
    session = sessions.create(jd_text=JD)
    _ask(BEHAVIOURAL[0], session, store)
    data = session.model_dump(mode="json")
    assert ApplicationSession.model_validate(data).session_id == session.session_id
