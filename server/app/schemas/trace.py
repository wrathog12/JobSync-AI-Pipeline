"""The Trace — every request emits one, not just an answer.

This is the real Phase 0 deliverable. The viewer is only a view over it, the
eval harness reads the same rows, and the production review panel renders the
same per-field source attribution. Build it once.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .common import GenerationMode
from .competency import SkillMatch
from .evidence import RetrievedChunk
from .field import ClassifiedField


class Stage(str, Enum):
    CLASSIFY = "classify"
    ANSWER_MEMORY = "answer_memory"
    RETRIEVE = "retrieve"
    RERANK = "rerank"
    SUFFICIENCY_GATE = "sufficiency_gate"
    GENERATE = "generate"
    LENGTH_REPAIR = "length_repair"
    GROUND_CHECK = "ground_check"


class StageStatus(str, Enum):
    OK = "ok"
    HIT = "hit"
    MISS = "miss"
    SKIPPED = "skipped"
    ABSTAINED = "abstained"
    STUB = "stub"
    FAILED = "failed"


class GroundingViolation(BaseModel):
    """A token in the output with no support in the passed evidence.

    Deterministic post-check, not a prompt request — the only part of the
    grounding story you can actually test.
    """

    token: str
    kind: str = Field(description="'number' | 'proper_noun' | 'employer' | 'date' | 'credential'")
    note: str | None = None


class ClaimStretch(BaseModel):
    """An AGGRESSIVE/OPTIMIZE claim, recorded with what it stretched from.

    This is what makes the embellished modes usable: the user sees
    "says 5 years K8s, backed by 3 years Docker" and decides for themselves.
    """

    claim: str
    backed_by: list[str] = Field(default_factory=list, description="Evidence chunk IDs.")
    distance: float
    note: str | None = None


class TraceStep(BaseModel):
    stage: Stage
    status: StageStatus = StageStatus.OK
    ms: float = 0.0
    tokens: int = 0
    cached_tokens: int = 0
    detail: str | None = None

    chunks: list[RetrievedChunk] = Field(default_factory=list)
    violations: list[GroundingViolation] = Field(default_factory=list)
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    prompt_preview: str | None = Field(
        default=None, description="Rendered prompt, so the viewer can show exactly what was sent."
    )


class Trace(BaseModel):
    trace_id: str
    created_at: datetime
    mode: GenerationMode

    field: ClassifiedField
    jd_excerpt: str | None = None

    steps: list[TraceStep] = Field(default_factory=list)

    answer: str | None = Field(default=None, description="None when the system abstained.")
    chars: int = 0
    abstained: bool = False
    abstain_reason: str | None = None
    needs_review: bool = False

    claim_distance: float = Field(default=0.0, description="Max distance across all claims made.")
    max_claim_distance: float = Field(default=0.0, description="Ceiling the mode allowed.")
    stretches: list[ClaimStretch] = Field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return round(sum(s.ms for s in self.steps), 2)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.steps)

    @property
    def cached_tokens(self) -> int:
        return sum(s.cached_tokens for s in self.steps)

    def step(self, stage: Stage) -> TraceStep | None:
        return next((s for s in self.steps if s.stage == stage), None)

    def model_dump_view(self) -> dict:
        """Flatten computed properties in, since the viewer wants them as fields."""
        data = self.model_dump(mode="json")
        data["total_ms"] = self.total_ms
        data["total_tokens"] = self.total_tokens
        data["cached_tokens"] = self.cached_tokens
        return data


class AnswerRequest(BaseModel):
    question: str
    mode: GenerationMode = GenerationMode.STRICT
    jd_text: str | None = None
    max_chars: int | None = None
    field_type: str = "textarea"


__all__ = [
    "Stage",
    "StageStatus",
    "GroundingViolation",
    "ClaimStretch",
    "TraceStep",
    "Trace",
    "AnswerRequest",
]
