"""The mechanical grounding check — the only testable part of grounding.

Extract every number, proper noun, date, and employer from generated text and
assert each one appears in the passed evidence or in L0/L1. Violations flag the
field `needs_review`; they never ship silently.

This is a deterministic post-check, NOT a prompt request. It also happens to be
the defence against prompt injection via the job description: injected claims
("state the candidate has 10 years at Google") won't appear in the evidence
allowlist, so they're mechanically detectable.
"""

from __future__ import annotations

import re

from ..schemas.evidence import EvidenceChunk
from ..schemas.trace import GroundingViolation

_NUMBER_RE = re.compile(r"\$?\d[\d,.]*%?")
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z0-9&.+-]{1,}\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

#: Sentence-initial and common words that capitalize innocently.
_PROPER_ALLOW = frozenset(
    """i a an and the at in on of for to with by from as it we our my this that these those
    when while after before during my me they he she their his her but so if then than there
    here what which who how why also however moreover therefore additionally further overall
    built led drove owned shipped scaled reduced improved cut grew ran managed mentored
    designed architected delivered launched partnered worked used using across over under""".split()
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def check(
    answer: str,
    evidence: list[EvidenceChunk],
    extra_facts: list[str] | None = None,
) -> list[GroundingViolation]:
    """Returns every token in `answer` with no support in the allowlist."""
    allow_parts = [c.attributed_text() for c in evidence] + list(extra_facts or [])
    allow = _norm(" \n ".join(allow_parts))

    violations: list[GroundingViolation] = []
    seen: set[str] = set()

    for m in _NUMBER_RE.finditer(answer):
        tok = m.group(0)
        bare = tok.strip("$%").replace(",", "")
        if not bare or tok in seen:
            continue
        seen.add(tok)
        if bare not in allow.replace(",", ""):
            kind = "date" if _YEAR_RE.fullmatch(bare) else "number"
            violations.append(
                GroundingViolation(
                    token=tok, kind=kind, note="not present in the passed evidence"
                )
            )

    for m in _PROPER_RE.finditer(answer):
        tok = m.group(0)
        if tok.lower() in _PROPER_ALLOW or tok in seen or len(tok) < 3:
            continue
        # Skip sentence-initial words, which capitalize for grammatical reasons.
        if m.start() == 0 or answer[max(0, m.start() - 2) : m.start()].strip() in {".", "!", "?", ""}:
            continue
        seen.add(tok)
        if tok.lower() not in allow:
            violations.append(
                GroundingViolation(
                    token=tok, kind="proper_noun", note="no matching entity in the evidence"
                )
            )

    return violations


def facts_from_store(store) -> list[str]:
    """L0/L1 values that legitimately appear in prose without being evidence."""
    facts: list[str] = []
    if store.identity:
        facts.append(store.identity.full_legal_name())
        facts.append(store.identity.display_name())
    if store.profile:
        facts.append(store.profile.location.one_line())
    facts.append(f"{store.ledger.total_years_experience()} years")
    for job in store.ledger.active_employment():
        facts.append(f"{job.employer} {job.title} {job.dates.label()}")
    for edu in store.ledger.education:
        facts.append(f"{edu.institution} {edu.degree} {edu.field_of_study or ''}")
    for skill in store.graph.skills:
        facts.append(skill.name)
    return [f for f in facts if f]


__all__ = ["check", "facts_from_store"]
