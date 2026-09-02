"""L4 — COMPETENCY GRAPH. Aggregated from L3 tags.

Two node kinds, and the distinction is the point:

- HARD skills are named things (Kubernetes, PostgreSQL, CPA). Normalized so
  React / ReactJS / React.js collapse to one node, with computed `years` and
  `last_used` so recency is a fact rather than a vibe.

- SOFT skills are NEVER declared. Nobody gets to tick "great communicator" —
  everyone does, and it's unfalsifiable. A soft skill exists only as a
  competency tag with a backing evidence count. Zero evidence means the system
  cannot answer a question about it and must abstain and ask the user, which
  turns a gap into onboarding instead of a fabrication.

This layer is also where a JD gets matched: `SkillDemand` records what the job
asked for, and `claim_distance` records how far the user's real evidence sits
from it. That distance is the only thing the generation modes disagree about.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SkillKind(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class Proficiency(str, Enum):
    EXPOSED = "exposed"
    WORKING = "working"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SkillNode(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(
        default_factory=list, description="['ReactJS', 'React.js'] -> one node."
    )
    kind: SkillKind = SkillKind.HARD
    category: str | None = Field(default=None, description="infra | language | tooling | domain …")

    years: float | None = None
    last_used: str | None = Field(default=None, description="YYYY-MM. Drives recency.")
    proficiency: Proficiency | None = None

    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Backing L3 chunks. Empty => a claim, not a fact.",
    )

    @property
    def is_backed(self) -> bool:
        """An unbacked skill is surfaced as unverified, never asserted."""
        return len(self.evidence_ids) > 0


class CompetencyNode(BaseModel):
    """A soft skill, expressed as evidence rather than as a claim."""

    tag: str
    label: str
    evidence_ids: list[str] = Field(default_factory=list)
    strongest_chunk_id: str | None = None

    @property
    def evidence_count(self) -> int:
        return len(self.evidence_ids)

    @property
    def is_answerable(self) -> bool:
        """Below 1, a behavioural question on this competency must abstain."""
        return self.evidence_count >= 1

    @property
    def is_thin(self) -> bool:
        """Answerable but worth warning the user about."""
        return self.evidence_count == 1


class SkillDemand(BaseModel):
    """One requirement parsed out of a job description."""

    raw_text: str
    normalized_name: str
    required_years: float | None = None
    is_required: bool = True


class SkillMatch(BaseModel):
    """The bridge between what the JD wants and what the user actually has.

    `distance` is the load-bearing number in the whole system:
        0.0  held, with direct evidence at or above the demanded level
        ~0.3 held but thinner than demanded, or reframable from real evidence
        ~0.7 adjacent / transferable but not actually held
        1.0  no relationship to anything in the profile
    """

    demand: SkillDemand
    matched_skill_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    distance: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Human-readable, e.g. 'adjacent: 3y Docker, no K8s'")

    def permitted_under(self, max_distance: float) -> bool:
        return self.distance <= max_distance


class CompetencyGraph(BaseModel):
    skills: list[SkillNode] = Field(default_factory=list)
    competencies: list[CompetencyNode] = Field(default_factory=list)

    def skill_by_name(self, name: str) -> SkillNode | None:
        needle = name.strip().lower()
        for s in self.skills:
            if s.name.lower() == needle or needle in (a.lower() for a in s.aliases):
                return s
        return None

    def competency(self, tag: str) -> CompetencyNode | None:
        return next((c for c in self.competencies if c.tag == tag), None)

    def unbacked_skills(self) -> list[SkillNode]:
        """Surfaced in the UI as 'you claimed these but gave us no example'."""
        return [s for s in self.skills if not s.is_backed]

    def gaps(self) -> list[CompetencyNode]:
        """Competencies with zero evidence. These are the onboarding prompts."""
        return [c for c in self.competencies if not c.is_answerable]


__all__ = [
    "SkillKind",
    "Proficiency",
    "SkillNode",
    "CompetencyNode",
    "SkillDemand",
    "SkillMatch",
    "CompetencyGraph",
]
