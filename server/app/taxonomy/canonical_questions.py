"""Canonical question IDs + the alias dictionary that resolves real labels to them.

This is tier 2 of the classification cascade (after the ATS adapter map, before
any LLM call). It is free, it covers most of what forms actually ask, and every
hit it scores is a field that never reaches a model.

`profile_path` is what makes a question DETERMINISTIC: it names the L0/L1/L2 key
to read. A question with no path and no attestation match is GENERATIVE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas.field import FieldClass


@dataclass(frozen=True)
class CanonicalQuestion:
    id: str
    label: str
    field_class: FieldClass
    profile_path: str | None = None
    aliases: tuple[str, ...] = ()
    competency_tags: tuple[str, ...] = ()


QUESTIONS: tuple[CanonicalQuestion, ...] = (
    # ── DETERMINISTIC: key lookup, zero tokens, ~70-80% of real fields ──
    CanonicalQuestion(
        "first_name", "First name", FieldClass.DETERMINISTIC, "identity.legal_first",
        ("first name", "given name", "forename", "legal first name"),
    ),
    CanonicalQuestion(
        "last_name", "Last name", FieldClass.DETERMINISTIC, "identity.legal_last",
        ("last name", "surname", "family name", "legal last name"),
    ),
    CanonicalQuestion(
        "full_name", "Full name", FieldClass.DETERMINISTIC, "identity.full_legal_name",
        ("full name", "your name", "name", "legal name", "candidate name"),
    ),
    CanonicalQuestion(
        "preferred_name", "Preferred name", FieldClass.DETERMINISTIC, "identity.preferred_name",
        ("preferred name", "nickname", "what should we call you"),
    ),
    CanonicalQuestion(
        "email", "Email", FieldClass.DETERMINISTIC, "profile.email",
        ("email", "e-mail", "email address", "contact email"),
    ),
    CanonicalQuestion(
        "phone", "Phone", FieldClass.DETERMINISTIC, "profile.phone_e164",
        ("phone", "telephone", "mobile", "phone number", "contact number", "cell"),
    ),
    CanonicalQuestion(
        "city", "City", FieldClass.DETERMINISTIC, "profile.location.city",
        ("city", "town", "current city"),
    ),
    CanonicalQuestion(
        "country", "Country", FieldClass.DETERMINISTIC, "profile.location.country",
        ("country", "country of residence"),
    ),
    CanonicalQuestion(
        "postal_code", "Postal code", FieldClass.DETERMINISTIC, "profile.location.postal",
        ("postal code", "zip", "zip code", "postcode"),
    ),
    CanonicalQuestion(
        "linkedin", "LinkedIn", FieldClass.DETERMINISTIC, "profile.links.linkedin",
        ("linkedin", "linkedin profile", "linkedin url"),
    ),
    CanonicalQuestion(
        "github", "GitHub", FieldClass.DETERMINISTIC, "profile.links.github",
        ("github", "github profile", "github url"),
    ),
    CanonicalQuestion(
        "portfolio", "Portfolio", FieldClass.DETERMINISTIC, "profile.links.portfolio",
        ("portfolio", "website", "personal site", "portfolio url"),
    ),
    CanonicalQuestion(
        "current_employer", "Current employer", FieldClass.DETERMINISTIC,
        "ledger.employment.current.employer",
        ("current employer", "current company", "present employer"),
    ),
    CanonicalQuestion(
        "current_title", "Current title", FieldClass.DETERMINISTIC,
        "ledger.employment.current.title",
        ("current title", "current role", "job title", "present title"),
    ),
    CanonicalQuestion(
        "years_experience", "Years of experience", FieldClass.DETERMINISTIC,
        "ledger.total_years_experience",
        ("years of experience", "total experience", "years of relevant experience"),
    ),
    CanonicalQuestion(
        "notice_period", "Notice period", FieldClass.DETERMINISTIC,
        "profile.preferences.notice_period_days",
        ("notice period", "availability to start", "when can you start"),
    ),
    CanonicalQuestion(
        "desired_salary", "Desired salary", FieldClass.DETERMINISTIC,
        "profile.preferences.desired_comp",
        ("desired salary", "expected salary", "salary expectation", "compensation expectation"),
    ),
    CanonicalQuestion(
        "willing_to_relocate", "Willing to relocate", FieldClass.DETERMINISTIC,
        "profile.preferences.willing_to_relocate",
        ("willing to relocate", "open to relocation", "relocate"),
    ),
    CanonicalQuestion(
        "highest_degree", "Highest degree", FieldClass.DETERMINISTIC, "ledger.education.latest.degree",
        ("highest degree", "degree", "level of education", "highest level of education"),
    ),
    CanonicalQuestion(
        "school", "School", FieldClass.DETERMINISTIC, "ledger.education.latest.institution",
        ("school", "university", "college", "institution"),
    ),

    # ── GENERATIVE: needs evidence + prose ──
    CanonicalQuestion(
        "why_this_role", "Why this role?", FieldClass.GENERATIVE, None,
        ("why do you want this role", "why this position", "why are you interested",
         "why do you want to work here", "why this company"),
        ("customer_focus", "communication"),
    ),
    CanonicalQuestion(
        "cover_letter", "Cover letter", FieldClass.GENERATIVE, None,
        ("cover letter", "additional information", "anything else",
         "tell us about yourself", "introduce yourself"),
        ("communication",),
    ),
    CanonicalQuestion(
        "technical_challenge", "A technical challenge you solved", FieldClass.GENERATIVE, None,
        ("technical challenge", "hardest problem", "difficult technical problem",
         "describe a challenge", "most challenging project"),
        ("technical_depth", "ownership", "ambiguity"),
    ),
    CanonicalQuestion(
        "leadership_example", "A leadership example", FieldClass.GENERATIVE, None,
        ("leadership example", "time you led", "led a team", "describe your leadership"),
        ("leadership", "influence_without_authority", "mentorship"),
    ),
    CanonicalQuestion(
        "conflict_example", "A disagreement you navigated", FieldClass.GENERATIVE, None,
        ("disagreement", "conflict with a coworker", "difficult colleague",
         "time you disagreed"),
        ("conflict_resolution", "communication", "stakeholder_management"),
    ),
    CanonicalQuestion(
        "failure_example", "A failure and what you learned", FieldClass.GENERATIVE, None,
        ("a failure", "mistake you made", "something that went wrong",
         "time you failed", "biggest weakness", "what you learned", "did not go well",
         "setback"),
        ("failure_and_learning", "ownership"),
    ),
    CanonicalQuestion(
        "influence_example", "Influencing without authority", FieldClass.GENERATIVE, None,
        ("influence stakeholders", "without direct authority", "persuade",
         "convince a team", "buy-in"),
        ("influence_without_authority", "stakeholder_management", "communication"),
    ),
    CanonicalQuestion(
        "relevant_experience", "Relevant experience for this role", FieldClass.GENERATIVE, None,
        ("relevant experience", "why are you a good fit", "what makes you qualified",
         "how does your experience relate"),
        ("technical_depth", "technical_breadth"),
    ),
    CanonicalQuestion(
        "proudest_project", "Proudest project", FieldClass.GENERATIVE, None,
        ("proudest", "best project", "favorite project", "most proud of",
         "accomplishment you are proud of"),
        ("ownership", "innovation", "technical_depth"),
    ),
)

_BY_ID = {q.id: q for q in QUESTIONS}
_NORMALIZE_RE = re.compile(r"[^a-z0-9\s]+")

#: Grammatical glue stripped before alias matching, so "something that went
#: wrong" still matches "...a time something went wrong...". Substring matching
#: was too brittle for this: one filler word broke the whole lookup.
#:
#: Deliberately NOT the same set as `derive.STOPWORDS`. That one indexes
#: evidence for BM25; this one normalizes question phrasing. Different jobs.
QUESTION_NOISE: frozenset[str] = frozenset(
    """a an the of for to that this these those is was are were be been am do did does
    have has had would could should will can may your you my our their its it and or
    in on at as with please kindly what which whats""".split()
)

#: A single-content-word alias may only match a label that is essentially just
#: that word. Real form labels are short ("Name", "Email"), so this costs nothing
#: — and without it, the unigram alias "name" resolves "What is the name of your
#: current manager?" to the user's own legal name and fills it. A confident,
#: wrong DETERMINISTIC answer is worse than no answer, so this errs short.
MAX_LABEL_TOKENS_FOR_UNIGRAM_ALIAS = 2

#: Alias matching requires a FULL subset of the alias's content words. A partial
#: (coverage-ratio) match was tried and reverted: allowing 3-of-4 words let the
#: generic opener "tell us about [yourself]" match "tell us about a time you
#: mentored someone", routing a mentorship question to `cover_letter` at 0.81.
#:
#: The lesson generalises. Aliases share their low-information words — "tell",
#: "describe", "experience" — so any partial match is dominated by boilerplate,
#: and a confidently wrong canonical ID is worse than no ID at all. Robustness to
#: phrasing belongs in `competency_hints` (which only widens retrieval) and later
#: in the tier-2 LLM classifier, NOT in loosening this table.
#:
#: Suffix rewrites, longest-first. Deliberately a fixed table rather than a real
#: stemmer: form labels are short and a heavier stemmer would collapse words that
#: must stay distinct in a DETERMINISTIC lookup.
_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("ships", ""),
    ("ship", ""),
    ("ments", ""),
    ("ment", ""),
    ("ies", "y"),
    ("ing", ""),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
)
_MIN_STEM = 4


def normalize(label: str) -> str:
    return " ".join(_NORMALIZE_RE.sub(" ", label.lower()).split())


def stem(token: str) -> str:
    """Collapse inflections so "mentored", "mentoring" and "mentorship" all match "mentor".

    Without this the alias table needs every inflection of every word written out
    by hand, and the one you forget is the one the form uses.
    """
    for suffix, replacement in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) + len(replacement) >= _MIN_STEM:
            token = token[: len(token) - len(suffix)] + replacement
            break
    # "manage"/"managing" both reach "manag" only if the silent -e goes too.
    if token.endswith("e") and len(token) > _MIN_STEM:
        token = token[:-1]
    return token


def _content_tokens(text: str) -> list[str]:
    return [stem(t) for t in normalize(text).split() if t not in QUESTION_NOISE]


def content_stems(text: str) -> list[str]:
    """Public view of the tokenizer, so the competency hinter stems identically.

    Two tokenizers would drift, and the drift would be invisible: a hint keyed on
    "mentor" would silently stop firing the day this one changed.
    """
    return _content_tokens(text)


def by_id(question_id: str) -> CanonicalQuestion | None:
    return _BY_ID.get(question_id)


def resolve(label: str) -> tuple[CanonicalQuestion | None, float]:
    """Alias-dictionary lookup on stemmed content tokens. Returns (question, confidence).

    An alias matches when enough of its content words appear in the label, in any
    order. Longer aliases score higher, because they are stronger evidence, and a
    partial match scores below an exact one so a shorter exact alias still wins.
    """
    label_tokens = _content_tokens(label)
    if not label_tokens:
        return None, 0.0
    label_set = set(label_tokens)

    best: CanonicalQuestion | None = None
    best_score = 0.0

    for q in QUESTIONS:
        for alias in q.aliases:
            a_tokens = _content_tokens(alias)
            if not a_tokens:
                continue
            a_set = set(a_tokens)
            if not a_set.issubset(label_set):
                continue

            if len(a_set) == 1 and len(label_tokens) > MAX_LABEL_TOKENS_FOR_UNIGRAM_ALIAS:
                continue

            if a_set == label_set:
                return q, 1.0

            score = min(0.95, 0.45 + 0.17 * len(a_set))
            if score > best_score:
                best, best_score = q, score

    return best, round(best_score, 3)


def all_questions() -> tuple[CanonicalQuestion, ...]:
    return QUESTIONS


__all__ = [
    "CanonicalQuestion",
    "QUESTIONS",
    "normalize",
    "by_id",
    "resolve",
    "all_questions",
]
