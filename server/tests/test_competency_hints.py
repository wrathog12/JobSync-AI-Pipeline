"""Competency tagging of questions that match no canonical alias.

The bug this pins: "Describe a situation where you had to influence people
without authority" matched no alias, so it reached retrieval with zero competency
tags, fell back to raw BM25, and abstained on evidence the profile plainly had.

The failed first attempt is pinned too. Loosening alias matching to a coverage
ratio fixed that question and broke a worse one — the generic opener "tell us
about [yourself]" started matching "tell us about a time you mentored someone",
routing a mentorship question to `cover_letter`. Hence the split: alias matching
stays exact and decides WHICH question this is; hints are generous and only
decide what it is ABOUT.
"""

from __future__ import annotations

import pytest

from app.memory.store import get_store
from app.pipeline.answer import run
from app.pipeline.classify import classify
from app.schemas.field import FieldClass, FieldType, FormField
from app.schemas.trace import AnswerRequest, Stage
from app.taxonomy import canonical_questions as cq
from app.taxonomy import competencies as comp_tax

UNALIASED = {
    "Describe a situation where you had to influence people without authority.": (
        "influence_without_authority"
    ),
    "Tell us about a time you mentored someone.": "mentorship",
    "Walk us through a disagreement you had with a colleague.": "conflict_resolution",
    "When did you last get something badly wrong?": "failure_and_learning",
    "How do you decide what not to work on?": "prioritization",
    "Give an example of improving a slow process.": "process_improvement",
}


@pytest.mark.parametrize("label,expected_tag", UNALIASED.items())
def test_unaliased_behavioural_questions_still_get_tags(label: str, expected_tag: str) -> None:
    field = classify(FormField(id="f1", type=FieldType.TEXTAREA, context_label=label))
    assert field.field_class is FieldClass.GENERATIVE
    assert expected_tag in field.competency_tags, f"{label!r} -> {field.competency_tags}"


def test_hints_do_not_hijack_a_canonical_match() -> None:
    """The reverted bug: partial alias matching sent a mentorship question to cover_letter."""
    q, score = cq.resolve("Tell us about a time you mentored someone.")
    assert q is None or q.id != "cover_letter", f"resolved to {q.id} at {score}"


def test_curated_tags_are_not_widened_by_hints() -> None:
    """Hints are a FALLBACK. Unioning them into alias hits took this question from
    3 tags to 8, widening the competency prefilter until it stopped filtering."""
    field = classify(
        FormField(
            id="f1",
            type=FieldType.TEXTAREA,
            context_label="Tell us about a time you led a team through a difficult migration.",
        )
    )
    assert field.classified_via == "alias_dict"
    assert len(field.competency_tags) <= 4, field.competency_tags


def test_hinted_questions_report_how_they_were_classified() -> None:
    field = classify(
        FormField(
            id="f1",
            type=FieldType.TEXTAREA,
            context_label="Tell us about a time you mentored someone.",
        )
    )
    assert field.classified_via == "competency_hints"
    assert field.classifier_confidence > 0.35, "a hinted match is stronger than bare prose"


def test_a_question_with_no_recognisable_topic_still_falls_back_to_prose() -> None:
    """Hints must stay silent rather than guess. No tags is a valid outcome."""
    field = classify(
        FormField(id="f1", type=FieldType.TEXTAREA, context_label="What are your hobbies?")
    )
    assert field.field_class is FieldClass.GENERATIVE
    assert field.classified_via == "heuristic_prose"
    assert field.competency_tags == []


def test_hints_never_invent_tags_outside_the_taxonomy() -> None:
    for tags in comp_tax.QUESTION_HINTS.values():
        for tag in tags:
            assert comp_tax.is_valid(tag), f"{tag} is not in COMPETENCIES"


def test_hints_do_not_route_an_attestation_question_to_generative() -> None:
    """The deny-list runs first and must stay ahead of anything that answers."""
    for label in (
        "Do you now or will you in the future require sponsorship?",
        "Have you ever been convicted of a felony? Explain the circumstances.",
    ):
        field = classify(FormField(id="f1", type=FieldType.TEXTAREA, context_label=label))
        assert field.field_class is FieldClass.ATTESTATION, label


# ── stemming ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "a,b",
    [
        ("mentored", "mentor"),
        ("mentoring", "mentor"),
        ("mentorship", "mentor"),
        ("managing", "manage"),
        ("authorities", "authority"),
        ("influenced", "influence"),
        ("names", "name"),
    ],
)
def test_stem_collapses_inflections(a: str, b: str) -> None:
    assert cq.stem(a) == cq.stem(b), f"{a} and {b} should stem alike"


def test_stem_leaves_short_words_alone() -> None:
    """Over-stemming would collide words that must stay distinct in a key lookup."""
    for word in ("name", "city", "gpa", "dob"):
        assert cq.stem(word) == word


def test_deterministic_lookups_survive_stemming() -> None:
    """Stemming must not blur one DETERMINISTIC field into another."""
    for label, expected in (
        ("First name", "first_name"),
        ("Last name", "last_name"),
        ("Email address", "email"),
        ("Phone number", "phone"),
    ):
        q, score = cq.resolve(label)
        assert q is not None and q.id == expected, f"{label!r} -> {q and q.id} @ {score}"


# ── the end-to-end effect ──────────────────────────────────────────────────────


def test_hinted_question_no_longer_falsely_abstains() -> None:
    """The whole point: this question used to abstain on evidence that exists."""
    store = get_store()
    trace = run(
        AnswerRequest(
            question="Describe a situation where you had to influence people without authority.",
            max_chars=400,
        ),
        store,
        None,
    )
    assert not trace.abstained, trace.abstain_reason
    retrieve = trace.step(Stage.RETRIEVE)
    assert retrieve is not None
    assert any(
        "influence_without_authority" in c.competency_overlap for c in retrieve.chunks
    ), "the tag filter should have done the work, not lexical luck"
