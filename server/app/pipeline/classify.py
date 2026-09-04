"""The classification cascade — tiered, cheapest first, and it fails closed.

    1. ATTESTATION deny-list      free   — checked FIRST, always
    2. Alias dictionary           free   — ~most of what forms actually ask
    3. (Phase 1) LLM classifier   cached by hash(domain + label + type)
    4. Below the floor            -> ATTESTATION, never GENERATIVE

Everything routes off this. A misclassification is a wasted call at best and a
legal problem at worst, which is why the deny-list runs before anything that
could produce a confident answer.
"""

from __future__ import annotations

from ..schemas.field import ClassifiedField, FieldClass, FieldType, FormField
from ..taxonomy import attestation
from ..taxonomy import canonical_questions as cq
from ..taxonomy import competencies as comp_tax

#: Below this, the alias hit is not trusted and we fall through.
ALIAS_FLOOR = 0.55

#: A long free-text field that clears the deny-list is almost certainly a prose
#: question. A short input we cannot identify could be anything, including
#: something sensitive — so that one fails closed.
PROSE_MIN_CHARS = 120


def classify(field: FormField) -> ClassifiedField:
    # ── Tier 1: deny-list, before anything else ──
    resolved, confidence = cq.resolve(field.context_label)
    candidate_id = resolved.id if resolved and confidence >= ALIAS_FLOOR else None

    if attestation.is_attestation(field.context_label, candidate_id):
        return ClassifiedField(
            **field.model_dump(),
            field_class=FieldClass.ATTESTATION,
            canonical_question_id=candidate_id,
            classified_via="attestation_denylist",
            classifier_confidence=1.0,
        )

    # ── Tier 2: alias dictionary ──
    if resolved and confidence >= ALIAS_FLOOR:
        # Curated tags win outright; hints are NOT unioned in here. Tried that,
        # and it took "led a team through a difficult migration" from 3 tags to 8
        # ("difficult", "team" and "migrate" each contributing), which widened the
        # competency prefilter until it stopped filtering. That prefilter being
        # narrow is the entire fix for lexical ranking returning the worst chunk.
        return ClassifiedField(
            **field.model_dump(),
            field_class=resolved.field_class,
            canonical_question_id=resolved.id,
            competency_tags=list(resolved.competency_tags),
            classified_via="alias_dict",
            classifier_confidence=confidence,
            profile_path=resolved.profile_path,
        )

    # ── Tier 3 placeholder: the LLM classifier lands here in Phase 1 ──

    # ── Tier 4: fail closed, with one narrow exception ──
    looks_like_prose = field.type == FieldType.TEXTAREA or (
        (field.constraints.max_chars or 0) >= PROSE_MIN_CHARS
    )
    if looks_like_prose:
        # Tags do NOT require a canonical match. Without this an unrecognised
        # behavioural question reaches retrieval with nothing to filter on, falls
        # back to raw BM25, and abstains on evidence the profile plainly has.
        # Tags only widen retrieval — the sufficiency gate still has final say —
        # so being generous here is safe in a way that guessing an ID is not.
        hints = _hints(field.context_label)
        return ClassifiedField(
            **field.model_dump(),
            field_class=FieldClass.GENERATIVE,
            competency_tags=hints,
            classified_via="heuristic_prose" if not hints else "competency_hints",
            classifier_confidence=0.35 if not hints else 0.45,
        )

    return ClassifiedField(
        **field.model_dump(),
        field_class=FieldClass.ATTESTATION,
        classified_via="fail_closed",
        classifier_confidence=0.0,
    )


def _hints(label: str) -> list[str]:
    """Competency tags from question wording, via the same stemmer the aliases use."""
    return comp_tax.competency_hints(cq.content_stems(label))


def why_blocked(field: ClassifiedField) -> str | None:
    if field.field_class != FieldClass.ATTESTATION:
        return None
    if field.classified_via == "fail_closed":
        return (
            "could not be classified with confidence; treated as an attestation "
            "so it is never auto-filled"
        )
    return attestation.explain(field.context_label, field.canonical_question_id)


__all__ = ["classify", "why_blocked", "ALIAS_FLOOR", "PROSE_MIN_CHARS"]
