"""The competency taxonomy — fixed, small, and used for two jobs at once.

1. Tag every evidence chunk at ingest (one LLM pass per chunk, cached forever).
2. Classify every incoming behavioural question into the same space.

Retrieval then matches tag-to-tag instead of question-text-to-bullet-text, which
is the fix for the register mismatch: "tell us about influencing stakeholders
without authority" and "drove cross-team adoption of the design system across 4
squads" match semantically but share almost no vocabulary, so raw similarity
ranks a generic collaboration bullet above the right one.

Keep this list stable. Changing a tag means re-tagging the whole corpus.
"""

from __future__ import annotations

COMPETENCIES: dict[str, str] = {
    "leadership": "Leading people or initiatives",
    "influence_without_authority": "Persuading peers or seniors you don't manage",
    "conflict_resolution": "Navigating disagreement between people",
    "ambiguity": "Making progress without clear requirements",
    "technical_depth": "Deep expertise in a specific technical area",
    "technical_breadth": "Working effectively across many technologies",
    "failure_and_learning": "Owning a failure and what changed after it",
    "mentorship": "Growing other people's capability",
    "ownership": "Taking end-to-end responsibility for an outcome",
    "customer_focus": "Working from user or customer need backwards",
    "scale": "Operating at high volume, traffic, or headcount",
    "process_improvement": "Making a system or workflow measurably better",
    "collaboration": "Working across teams or functions",
    "communication": "Explaining complex things to the right audience",
    "prioritization": "Choosing what not to do under constraint",
    "data_driven": "Deciding from measurement rather than intuition",
    "innovation": "Building something that did not exist before",
    "reliability": "Improving stability, uptime, or correctness",
    "cost_efficiency": "Reducing spend or resource consumption",
    "stakeholder_management": "Managing expectations upward and outward",
}

#: Competencies that are pure soft skills. These may ONLY be surfaced with
#: backing evidence — never as a user-declared checkbox.
SOFT_COMPETENCIES: frozenset[str] = frozenset(
    {
        "leadership",
        "influence_without_authority",
        "conflict_resolution",
        "ambiguity",
        "failure_and_learning",
        "mentorship",
        "ownership",
        "customer_focus",
        "collaboration",
        "communication",
        "prioritization",
        "stakeholder_management",
    }
)


#: Question-side keyword hints: label wording -> competency tags.
#:
#: This exists because competency tags must NOT depend on resolving a question to
#: a canonical ID. "Describe a situation where you had to influence people
#: without authority" matches no alias in the question table, so it arrived at
#: retrieval with zero tags, fell back to pure lexical ranking, and abstained on
#: evidence the profile plainly had.
#:
#: Two different jobs, deliberately separated:
#:   - the canonical table answers "WHICH question is this", and must be precise,
#:     because a wrong ID means a wrong DETERMINISTIC fill or a wrong L5 reuse;
#:   - this map answers "what is this question ABOUT", and can afford to be
#:     generous, because its only effect is widening the retrieval pool. The
#:     sufficiency gate still decides whether the result is good enough.
#:
#: Keys are matched as stems against the question's words, so "mentored",
#: "mentoring" and "mentorship" all reach "mentor".
#:
#: PHASE 1 TASK: this is the keyword stand-in for the tier-2 LLM classifier, the
#: same way `derive._TAG_HINTS` stands in for the LLM chunk tagger. Both should be
#: measured against a labelled set before anyone trusts them.
QUESTION_HINTS: dict[str, tuple[str, ...]] = {
    "influenc": ("influence_without_authority", "communication"),
    "persuad": ("influence_without_authority", "communication"),
    "convinc": ("influence_without_authority", "communication"),
    "buy": ("influence_without_authority", "stakeholder_management"),
    "authorit": ("influence_without_authority",),
    "stakehold": ("stakeholder_management", "communication"),
    "upward": ("stakeholder_management",),
    "mentor": ("mentorship", "leadership"),
    "coach": ("mentorship", "leadership"),
    "junior": ("mentorship",),
    "onboard": ("mentorship", "process_improvement"),
    "taught": ("mentorship", "communication"),
    "teach": ("mentorship", "communication"),
    "led": ("leadership", "ownership"),
    "lead": ("leadership", "ownership"),
    "manag": ("leadership", "stakeholder_management"),
    "team": ("leadership", "collaboration"),
    "disagre": ("conflict_resolution", "communication"),
    "conflict": ("conflict_resolution",),
    "pushback": ("conflict_resolution", "influence_without_authority"),
    "difficult": ("conflict_resolution", "ambiguity"),
    "tension": ("conflict_resolution",),
    "fail": ("failure_and_learning", "ownership"),
    "mistak": ("failure_and_learning", "ownership"),
    "wrong": ("failure_and_learning",),
    "learn": ("failure_and_learning",),
    "postmortem": ("failure_and_learning", "reliability"),
    "outag": ("reliability", "failure_and_learning"),
    "incident": ("reliability", "failure_and_learning"),
    "uptim": ("reliability",),
    "reliabl": ("reliability",),
    "bug": ("reliability", "technical_depth"),
    "ambigu": ("ambiguity", "prioritization"),
    "unclear": ("ambiguity",),
    "uncertain": ("ambiguity",),
    "prioriti": ("prioritization", "ownership"),
    "decid": ("prioritization", "data_driven"),
    "decis": ("prioritization", "data_driven"),
    "chose": ("prioritization",),
    "deadlin": ("prioritization", "ownership"),
    "tradeoff": ("prioritization", "technical_depth"),
    "compet": ("prioritization",),
    "challeng": ("technical_depth", "ownership"),
    "technic": ("technical_depth",),
    "architect": ("technical_depth", "technical_breadth"),
    "debug": ("technical_depth", "reliability"),
    "complex": ("technical_depth", "communication"),
    "scal": ("scale", "technical_depth"),
    "volum": ("scale",),
    "traffic": ("scale", "reliability"),
    "perform": ("scale", "technical_depth"),
    "latenc": ("scale", "technical_depth"),
    "migrat": ("ownership", "technical_depth", "leadership"),
    "cross": ("collaboration", "influence_without_authority"),
    "collabor": ("collaboration",),
    "partner": ("collaboration", "stakeholder_management"),
    "cross-funct": ("collaboration",),
    "explain": ("communication",),
    "present": ("communication",),
    "wrote": ("communication",),
    "document": ("communication", "process_improvement"),
    "custom": ("customer_focus",),
    "user": ("customer_focus",),
    "improv": ("process_improvement",),
    "process": ("process_improvement",),
    "efficien": ("process_improvement", "cost_efficiency"),
    "cost": ("cost_efficiency",),
    "spend": ("cost_efficiency",),
    "budget": ("cost_efficiency", "prioritization"),
    "data": ("data_driven",),
    "metric": ("data_driven", "process_improvement"),
    "measur": ("data_driven",),
    "experiment": ("data_driven", "innovation"),
    "built": ("innovation", "ownership"),
    "creat": ("innovation", "ownership"),
    "new": ("innovation",),
    "innovat": ("innovation",),
    "own": ("ownership",),
    "responsib": ("ownership",),
    "end-to-end": ("ownership",),
    "initiativ": ("ownership", "leadership"),
}


def competency_hints(stems: list[str] | set[str]) -> list[str]:
    """Tags suggested by a question's stemmed words. Union, deduplicated, sorted.

    Generous by design: a wider retrieval pool costs a few milliseconds, while a
    missing tag costs a false abstention on evidence the user actually gave us.
    """
    words = set(stems)
    out: set[str] = set()
    for key, tags in QUESTION_HINTS.items():
        if key in words or any(w.startswith(key) for w in words):
            out.update(tags)
    return sorted(t for t in out if t in COMPETENCIES)


def is_valid(tag: str) -> bool:
    return tag in COMPETENCIES


def label(tag: str) -> str:
    return COMPETENCIES.get(tag, tag)


def all_tags() -> list[str]:
    return sorted(COMPETENCIES)


__all__ = [
    "COMPETENCIES",
    "SOFT_COMPETENCIES",
    "QUESTION_HINTS",
    "competency_hints",
    "is_valid",
    "label",
    "all_tags",
]
