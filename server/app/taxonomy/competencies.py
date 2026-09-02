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


def is_valid(tag: str) -> bool:
    return tag in COMPETENCIES


def label(tag: str) -> str:
    return COMPETENCIES.get(tag, tag)


def all_tags() -> list[str]:
    return sorted(COMPETENCIES)


__all__ = ["COMPETENCIES", "SOFT_COMPETENCIES", "is_valid", "label", "all_tags"]
