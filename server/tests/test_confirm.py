"""Confirmation-pass tests.

The one to read first is `test_a_rubber_stamped_hallucination_is_refused`. Every
other rule here protects a boundary; that one protects the premise. If a user can
click past an invented bullet, the evidence index contains model prose, the
grounding check then validates future claims against it, and every number this
system reports about its own accuracy is measuring a closed loop.
"""

from __future__ import annotations

import pytest

from app.memory.store import MemoryStore
from app.pipeline.answer import run
from app.pipeline.confirm import ConfirmRequest, confirm
from app.pipeline.structure import build_result
from app.schemas.common import Confidence, GenerationMode, Source
from app.schemas.field import FieldClass
from app.schemas.structured import CandidateAchievement
from app.schemas.trace import AnswerRequest
from tests.test_structure import RESUME, extracted, raw_doc


@pytest.fixture
def empty_store() -> MemoryStore:
    """A blank store, not the fixture singleton — confirmation writes to it."""
    return MemoryStore()


@pytest.fixture
def candidate():
    return build_result(extracted(), raw_doc())


def request_for(candidate, **overrides) -> ConfirmRequest:
    base = dict(
        doc_id=candidate.doc_id,
        result=candidate.model_copy(deep=True),
        accept_record_ids=[],
    )
    base.update(overrides)
    return ConfirmRequest(**base)


def all_record_ids(candidate) -> list[str]:
    led = candidate.ledger
    return [r.id for r in (*led.employment, *led.education, *led.projects, *led.credentials)]


# ── consent is explicit ────────────────────────────────────────────────────────


def test_nothing_is_committed_by_default(empty_store, candidate):
    """Omission is not consent. An empty request must be a no-op, not "accept all"."""
    res = confirm(request_for(candidate), candidate, empty_store, RESUME)
    assert res.records_committed == 0
    assert empty_store.ledger.employment == []
    assert empty_store.identity is None
    assert empty_store.profile is None
    assert res.identity_committed is False


def test_only_listed_records_are_committed(empty_store, candidate):
    keep = candidate.ledger.employment[0].id
    res = confirm(
        request_for(candidate, accept_record_ids=[keep]), candidate, empty_store, RESUME
    )
    assert res.employment_committed == 1
    assert [e.id for e in empty_store.ledger.employment] == [keep]
    assert empty_store.ledger.education == [], "not listed, so discarded"


def test_a_doc_id_mismatch_is_refused(empty_store, candidate):
    """The candidate is the server's copy; a request pointing at a different one
    would confirm records nobody reviewed."""
    bad = candidate.model_copy(deep=True)
    bad.doc_id = "doc_9999999999999999"
    with pytest.raises(ValueError, match="doc_id mismatch"):
        confirm(request_for(candidate, result=bad), candidate, empty_store, RESUME)


# ── the rule that makes confirmation more than a rubber stamp ──────────────────


def test_a_rubber_stamped_hallucination_is_refused(empty_store):
    """A bullet the model invented, accepted unchanged, must not become evidence.

    This is the failure the whole verification chain exists for: once committed it
    is indistinguishable from a real achievement, it becomes an L3 chunk, and the
    grounding check then treats it as the ground truth that future generated prose
    is measured against.

    Note where the invention has to come from: the *candidate*, i.e. the model's own
    output. That is the only shape this failure can take. A bullet appearing for the
    first time in the request cannot have been rubber-stamped, because there was
    nothing there to stamp — someone typed it.
    """
    doc = extracted()
    doc.employment[0].achievements.append(
        CandidateAchievement(text="Managed a team of twelve engineers.")
    )
    hallucinated = build_result(doc, raw_doc())
    assert hallucinated.unverified_quotes == 1, "structuring flagged it; confirmation must refuse it"

    res = confirm(
        request_for(hallucinated, accept_record_ids=[hallucinated.ledger.employment[0].id]),
        hallucinated,
        empty_store,
        RESUME,
    )

    texts = [a.text for a in empty_store.ledger.employment[0].achievements]
    assert not any("twelve engineers" in t for t in texts)
    assert len(res.rejections) == 1
    assert "unchanged" in res.rejections[0].reason
    assert res.achievements_committed == 2, "the genuine bullets still went in"


def test_a_bullet_added_in_review_is_the_users_own_words(empty_store, candidate):
    """The counterpart, and the reason the check compares text rather than counting.
    A bullet that only exists in the request was typed by the user in the review UI
    — the résumé is not the limit of what someone did, and a tool that refuses
    anything absent from the PDF cannot be used to add the project they forgot."""
    from app.schemas.ledger import Achievement

    submitted = candidate.model_copy(deep=True)
    submitted.ledger.employment[0].achievements.append(
        Achievement(id="ach_added_00", text="Ran the on-call rotation for eighteen months.")
    )
    res = confirm(
        request_for(
            candidate,
            result=submitted,
            accept_record_ids=[candidate.ledger.employment[0].id],
        ),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.rejections == []
    assert res.achievements_committed == 3
    assert res.achievements_user_authored == 1


def test_an_edited_bullet_is_accepted_as_the_users_own_words(empty_store, candidate):
    """The mirror case, and the reason the check is about *editing* rather than
    about matching the document. A sentence the user wrote about their own career is
    the best evidence in the system — refusing it because it is not in the PDF would
    make the tool worse than a text box."""
    submitted = candidate.model_copy(deep=True)
    submitted.ledger.employment[0].achievements[0].text = (
        "Cut median checkout latency from 840ms to 290ms — the 310ms figure was stale."
    )
    res = confirm(
        request_for(
            candidate,
            result=submitted,
            accept_record_ids=[candidate.ledger.employment[0].id],
        ),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.achievements_committed == 2
    assert res.achievements_user_authored == 1
    assert res.rejections == []
    assert "290ms" in empty_store.ledger.employment[0].achievements[0].text


def test_an_edited_record_is_marked_user_entered(empty_store, candidate):
    submitted = candidate.model_copy(deep=True)
    submitted.ledger.employment[0].title = "Principal Engineer"
    confirm(
        request_for(
            candidate,
            result=submitted,
            accept_record_ids=[candidate.ledger.employment[0].id],
        ),
        candidate,
        empty_store,
        RESUME,
    )
    assert empty_store.ledger.employment[0].provenance.source is Source.USER_ENTERED


def test_an_unedited_record_keeps_its_parsed_source(empty_store, candidate):
    """Confirmed, but honest about where it came from — the difference matters when
    something turns out wrong and the question is whether the parser or the user
    got it wrong."""
    confirm(
        request_for(candidate, accept_record_ids=[candidate.ledger.employment[0].id]),
        candidate,
        empty_store,
        RESUME,
    )
    assert empty_store.ledger.employment[0].provenance.source is Source.PARSED_RESUME


def test_confirmation_upgrades_confidence_but_not_to_verified(empty_store, candidate):
    """VERIFIED stays available for a fact checked against something external.
    Spending it on a button click would leave the stronger case inexpressible."""
    confirm(
        request_for(candidate, accept_record_ids=[candidate.ledger.employment[0].id]),
        candidate,
        empty_store,
        RESUME,
    )
    prov = empty_store.ledger.employment[0].provenance
    assert prov.confidence is Confidence.USER_STATED
    assert prov.confirmed_at is not None
    assert prov.is_confirmed is True


# ── append-only, idempotent ────────────────────────────────────────────────────


def test_confirming_the_same_document_twice_does_not_duplicate(empty_store, candidate):
    """Ids come from the document, so a double-click or a retried request is a
    no-op rather than a second copy of someone's career."""
    req = request_for(candidate, accept_record_ids=all_record_ids(candidate))
    first = confirm(req, candidate, empty_store, RESUME)
    second = confirm(req, candidate, empty_store, RESUME)

    # 2 employment + 1 education + 1 project + 0 credentials.
    assert first.records_committed == 4
    assert second.records_committed == 0
    assert set(second.skipped_existing) == set(all_record_ids(candidate))
    assert len(empty_store.ledger.employment) == 2


def test_a_correction_supersedes_without_deleting(empty_store, candidate):
    """L2's core claim. A wrong record that has already been used in an application
    is part of what was submitted, and that is the only way to answer "what did I
    tell them last time"."""
    old_id = candidate.ledger.employment[0].id
    confirm(
        request_for(candidate, accept_record_ids=[old_id]), candidate, empty_store, RESUME
    )

    corrected = build_result(extracted(), raw_doc(doc_id="doc_2222222222222222"))
    new_id = corrected.ledger.employment[0].id
    res = confirm(
        request_for(corrected, accept_record_ids=[new_id], supersedes={new_id: old_id}),
        corrected,
        empty_store,
        RESUME,
    )

    assert res.superseded == [old_id]
    old = next(e for e in empty_store.ledger.employment if e.id == old_id)
    assert old.superseded_by == new_id
    assert old.is_active is False
    assert len(empty_store.ledger.employment) == 2, "kept, not deleted"
    assert len(empty_store.ledger.active_employment()) == 1


def test_superseding_a_missing_record_still_saves_the_new_one(empty_store, candidate):
    """Losing the new record over a bad reference would be the worst of both."""
    new_id = candidate.ledger.employment[0].id
    res = confirm(
        request_for(
            candidate, accept_record_ids=[new_id], supersedes={new_id: "emp_nope_00"}
        ),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.employment_committed == 1
    assert any("emp_nope_00" in r.reason for r in res.rejections)


# ── L0 locks ───────────────────────────────────────────────────────────────────


def test_identity_locks_on_confirmation(empty_store, candidate):
    res = confirm(request_for(candidate, confirm_identity=True), candidate, empty_store, RESUME)
    assert res.identity_committed and res.identity_locked
    assert empty_store.identity is not None
    assert empty_store.identity.locked is True
    assert empty_store.identity.locked_at is not None
    assert empty_store.identity.full_legal_name() == "Priya Raghunathan"


def test_a_locked_identity_is_not_silently_overwritten(empty_store, candidate):
    confirm(request_for(candidate, confirm_identity=True), candidate, empty_store, RESUME)

    other = build_result(
        extracted(name=_name("Priyanka", "Raghunathan")), raw_doc(doc_id="doc_3333333333333333")
    )
    res = confirm(request_for(other, confirm_identity=True), other, empty_store, RESUME)

    assert res.identity_committed is False
    assert any("unlock" in r.reason for r in res.rejections)
    assert empty_store.identity.legal_first == "Priya"


def test_an_explicit_unlock_allows_a_real_name_change(empty_store, candidate):
    """Names change on marriage and naturalization. Modeling L0 as truly immutable
    buys a migration in year one; requiring a deliberate unlock does not."""
    confirm(request_for(candidate, confirm_identity=True), candidate, empty_store, RESUME)
    other = build_result(
        extracted(name=_name("Priya", "Menon")), raw_doc(doc_id="doc_4444444444444444")
    )
    res = confirm(
        request_for(other, confirm_identity=True, unlock_identity=True),
        other,
        empty_store,
        RESUME,
    )
    assert res.identity_committed is True
    assert empty_store.identity.legal_last == "Menon"
    assert empty_store.identity.locked is True, "re-locked, not left open"


def test_confirming_without_a_name_is_rejected_not_crashed(empty_store):
    nameless = build_result(extracted(name=None), raw_doc())
    res = confirm(request_for(nameless, confirm_identity=True), nameless, empty_store, RESUME)
    assert res.identity_committed is False
    assert empty_store.identity is None
    assert res.rejections


def _name(first: str, last: str):
    from app.schemas.structured import CandidateName

    return CandidateName(legal_first=first, legal_last=last)


# ── L1 ─────────────────────────────────────────────────────────────────────────


def test_accepted_profile_paths_are_committed_and_dated(empty_store, candidate):
    res = confirm(
        request_for(candidate, accept_profile_paths=["email", "location"]),
        candidate,
        empty_store,
        RESUME,
    )
    assert set(res.profile_paths_committed) == {"email", "location"}
    assert empty_store.profile.email == "priya.r@example.com"
    assert empty_store.profile.location.city == "San Francisco"
    # The staleness clock starts now; without this every freshly confirmed field
    # is reported stale the moment it is saved.
    assert "email" not in empty_store.profile.stale_paths()


def test_unaccepted_profile_fields_are_not_written(empty_store, candidate):
    confirm(
        request_for(candidate, accept_profile_paths=["email"]), candidate, empty_store, RESUME
    )
    assert empty_store.profile.email is not None
    assert empty_store.profile.phone_e164 is None, "not accepted, so not stored"


def test_work_authorization_cannot_be_confirmed_from_a_document(empty_store, candidate):
    """It never came from the document, so there is nothing to confirm. A request
    naming it is a bug, and an error says so instead of silently ignoring it."""
    res = confirm(
        request_for(candidate, accept_profile_paths=["authorization"]),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.profile_paths_committed == []
    reason = next(r.reason for r in res.rejections if r.record_id == "profile.authorization")
    assert "by hand" in reason
    from app.schemas.profile import AuthorizationStatus

    assert empty_store.profile.authorization.status is AuthorizationStatus.UNKNOWN


def test_preferences_cannot_be_confirmed_from_a_document(empty_store, candidate):
    res = confirm(
        request_for(candidate, accept_profile_paths=["preferences"]),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.profile_paths_committed == []
    assert res.rejections


# ── declared skills ────────────────────────────────────────────────────────────


def test_hard_skills_are_committed(empty_store, candidate):
    res = confirm(
        request_for(candidate, accept_skills=["Python", "Kubernetes"]),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.skills_committed == 2
    assert {s.name for s in empty_store.declared_skills} == {"Python", "Kubernetes"}


def test_a_soft_skill_cannot_be_declared(empty_store, candidate):
    """Nobody gets to tick "great communicator" — everyone would, and it is
    unfalsifiable. It exists only as a count of backing evidence, and a skills
    section listing it is not a reason to break that."""
    res = confirm(
        request_for(candidate, accept_skills=["Communication", "Leadership", "Go"]),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.skills_committed == 1
    assert {s.name for s in empty_store.declared_skills} == {"Go"}
    assert len(res.rejections) == 2
    assert any("demonstrate" in r.reason for r in res.rejections)


def test_duplicate_skills_are_not_added_twice(empty_store, candidate):
    req = request_for(candidate, accept_skills=["Python", "python"])
    res = confirm(req, candidate, empty_store, RESUME)
    assert res.skills_committed == 1


# ── derived layers ─────────────────────────────────────────────────────────────


def test_committing_rebuilds_the_derived_layers(empty_store, candidate):
    """L3/L4 are the only reason any of this is retrievable. A commit that skipped
    the rebuild would leave new records invisible, and the system would abstain on
    evidence it demonstrably has."""
    assert empty_store.evidence.chunks == []
    res = confirm(
        request_for(candidate, accept_record_ids=all_record_ids(candidate)),
        candidate,
        empty_store,
        RESUME,
    )
    assert res.evidence_chunks > 0
    assert len(empty_store.evidence.chunks) == res.evidence_chunks
    assert empty_store.graph.competencies, "the graph is rebuilt too"


def test_a_rejected_bullet_never_reaches_the_evidence_index(empty_store):
    """The end-to-end version of the premise: refusing it at confirmation has to
    mean it is not retrievable, not merely that it was flagged."""
    doc = extracted()
    doc.employment[0].achievements.append(
        CandidateAchievement(text="Saved the company from certain ruin.")
    )
    hallucinated = build_result(doc, raw_doc())
    confirm(
        request_for(hallucinated, accept_record_ids=all_record_ids(hallucinated)),
        hallucinated,
        empty_store,
        RESUME,
    )
    assert empty_store.evidence.chunks, "the real bullets did get indexed"
    assert not any("certain ruin" in c.text for c in empty_store.evidence.chunks)


def test_a_no_op_confirmation_does_not_rebuild(empty_store, candidate):
    """Cheap now, but the rebuild is O(all evidence) and this path is hit by every
    cancelled review."""
    empty_store.rebuild_derived()
    before = empty_store.evidence
    confirm(request_for(candidate), candidate, empty_store, RESUME)
    assert empty_store.evidence is before


# ── the gate this whole pass exists to satisfy ─────────────────────────────────


def test_an_unconfirmed_value_does_not_reach_a_form(empty_store, candidate):
    """Without this check the confirmation pass is decoration: a DETERMINISTIC fill
    is submitted verbatim with no review in front of it, so a misparsed employer
    name goes onto a real application under the user's name.
    """
    empty_store.profile = candidate.profile  # PARSED_UNCONFIRMED, straight from the parser
    empty_store.identity = candidate.identity
    empty_store.ledger = candidate.ledger
    empty_store.rebuild_derived()

    trace = run(
        AnswerRequest(question="Email address", mode=GenerationMode.STRICT, max_chars=200),
        empty_store,
    )
    assert trace.field.field_class is FieldClass.DETERMINISTIC
    assert trace.answer is None
    assert trace.abstained is True
    assert "confirmed" in trace.abstain_reason


def test_the_same_field_fills_itself_once_confirmed(empty_store, candidate):
    empty_store.ledger = candidate.ledger
    confirm(
        request_for(candidate, accept_profile_paths=["email"]), candidate, empty_store, RESUME
    )
    trace = run(
        AnswerRequest(question="Email address", mode=GenerationMode.STRICT, max_chars=200),
        empty_store,
    )
    assert trace.answer == "priya.r@example.com"
    assert trace.abstained is False


def test_an_aggregate_is_only_as_confirmed_as_its_inputs(empty_store, candidate):
    """`total_years_experience` is computed from every active job, so one
    unconfirmed record with a bad end date moves the number."""
    empty_store.ledger = candidate.ledger
    prov = empty_store.provenance_for("ledger.total_years_experience")
    assert prov is not None and prov.is_confirmed is False

    confirm(
        request_for(candidate, accept_record_ids=all_record_ids(candidate)),
        candidate,
        MemoryStore(),
        RESUME,
    )
    fresh = MemoryStore()
    confirm(
        request_for(candidate, accept_record_ids=all_record_ids(candidate)),
        candidate,
        fresh,
        RESUME,
    )
    assert fresh.provenance_for("ledger.total_years_experience").is_confirmed is True


def test_an_absent_record_is_unconfirmed_not_permitted(empty_store):
    """None must never read as permission."""
    assert empty_store.provenance_for("identity.legal_first") is None
    assert empty_store.provenance_for("ledger.employment.current.employer") is None
    assert empty_store.provenance_for("nonsense.path") is None
