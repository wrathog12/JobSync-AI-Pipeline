"""L5 — ANSWER MEMORY. Append-only, human-approved answers. The flywheel.

Not derived from anything: it's *earned* from user approvals. A hit costs zero
tokens, zero latency, and is already quality-checked by the user — which makes
this the highest-value index in the system and the reason marginal cost falls
with usage.

Keyed by canonical question, not by chunk, so it survives every L3/L4 rebuild.
The user's *edit* is the training signal; capturing it is the entire point.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import GenerationMode


class ApprovedAnswer(BaseModel):
    id: str
    canonical_question_id: str = Field(
        description="Stable ID from the question taxonomy. The lookup key."
    )
    raw_question: str = Field(description="Verbatim label as it appeared on the form.")

    company_id: str | None = None
    company_name: str | None = None

    answer_text: str
    char_count: int = 0
    mode_used: GenerationMode = GenerationMode.STRICT

    evidence_ids_used: list[str] = Field(default_factory=list)
    edited_by_user: bool = Field(
        default=False,
        description="True if the user changed the generated text. The signal worth mining.",
    )
    original_generated_text: str | None = Field(
        default=None, description="Kept when edited, so we can learn from the delta."
    )

    approved_at: datetime
    times_reused: int = 0
    embedding: list[float] | None = None


class AnswerMemory(BaseModel):
    answers: list[ApprovedAnswer] = Field(default_factory=list)

    def exact(self, canonical_question_id: str, company_id: str | None = None) -> ApprovedAnswer | None:
        """Company-specific first, then the company-agnostic fallback."""
        if company_id:
            hit = next(
                (
                    a
                    for a in self.answers
                    if a.canonical_question_id == canonical_question_id
                    and a.company_id == company_id
                ),
                None,
            )
            if hit:
                return hit
        return next(
            (
                a
                for a in self.answers
                if a.canonical_question_id == canonical_question_id and a.company_id is None
            ),
            None,
        )

    def hit_rate_target(self) -> float:
        """Phase 3 exit criterion: >60% by application #20."""
        return 0.60


__all__ = ["ApprovedAnswer", "AnswerMemory"]
