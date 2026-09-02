"""The ATTESTATION deny-list. Versioned, tested data — not a prompt instruction.

Some form fields are ones where a wrong answer is not a quality problem, it is
fraud. Asked "do you require sponsorship to work in the United States?", a model
with incomplete context produces a plausible answer — and that answer is a
signed legal attestation made by software on the user's behalf.

Two guarantees this module exists to provide:

1. **Fail closed.** An unclassifiable field is ATTESTATION, never GENERATIVE.
2. **No slot to answer into.** ATTESTATION fields are excluded from the
   generation response schema entirely. Don't instruct the model to decline —
   don't give it the option. That's a hard guarantee rather than a soft one.

Bump `VERSION` on every change; the tests pin behaviour against it.
"""

from __future__ import annotations

import re

VERSION = 1

#: Substring net over the normalized field label. Deliberately broad — a false
#: positive costs the user one manual field, a false negative can cost them a job.
KEYWORD_NET: tuple[str, ...] = (
    # work authorization / immigration
    "sponsor",
    "authoriz",
    "authoris",
    "visa",
    "work permit",
    "right to work",
    "eligible to work",
    "immigration",
    "citizenship",
    "green card",
    "h1b",
    "h-1b",
    "opt/cpt",
    # criminal / background
    "felony",
    "convict",
    "criminal",
    "background check",
    "background screen",
    "drug test",
    "misdemeanor",
    # protected characteristics (voluntary self-identification only)
    "veteran",
    "disab",
    "race",
    "ethnic",
    "gender",
    "sexual orientation",
    "religion",
    "pregnan",
    "marital status",
    "national origin",
    # verified credentials
    "gpa",
    "grade point",
    "clearance",
    "security clearance",
    "licen",  # licence / license / licensure
    "certif",
    "transcript",
    # compensation history (illegal to ask in several US jurisdictions)
    "salary histor",
    "current salary",
    "previous salary",
    "compensation histor",
    "pay histor",
    # explicit legal affirmations
    "i certify",
    "i attest",
    "i affirm",
    "under penalty",
    "true and complete",
    "e-signature",
    "electronic signature",
    "consent to",
    "agree to the terms",
)

#: Canonical question IDs that are always attestation, regardless of wording.
DENIED_QUESTION_IDS: frozenset[str] = frozenset(
    {
        "work_authorization",
        "requires_sponsorship",
        "visa_status",
        "criminal_history",
        "background_check_consent",
        "eeo_race",
        "eeo_gender",
        "eeo_veteran_status",
        "eeo_disability",
        "gpa",
        "security_clearance",
        "salary_history",
        "certification_affirmation",
        "drug_test_consent",
    }
)

_NORMALIZE_RE = re.compile(r"[^a-z0-9\s/-]+")


def normalize_label(label: str) -> str:
    return _NORMALIZE_RE.sub(" ", label.lower()).strip()


def matched_keywords(label: str) -> list[str]:
    norm = normalize_label(label)
    return [kw for kw in KEYWORD_NET if kw in norm]


def is_attestation(label: str, canonical_question_id: str | None = None) -> bool:
    """True if this field must never be auto-filled, under any circumstance."""
    if canonical_question_id and canonical_question_id in DENIED_QUESTION_IDS:
        return True
    return bool(matched_keywords(label))


def explain(label: str, canonical_question_id: str | None = None) -> str | None:
    """Why a field was blocked — shown to the user in the review panel."""
    if canonical_question_id and canonical_question_id in DENIED_QUESTION_IDS:
        return f"canonical question '{canonical_question_id}' is on the deny-list"
    hits = matched_keywords(label)
    if hits:
        return f"label matched deny-list keyword(s): {', '.join(hits)}"
    return None


__all__ = [
    "VERSION",
    "KEYWORD_NET",
    "DENIED_QUESTION_IDS",
    "normalize_label",
    "matched_keywords",
    "is_attestation",
    "explain",
]
