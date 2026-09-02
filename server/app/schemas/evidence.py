"""L3 — EVIDENCE INDEX. Derived from L2, fully rebuildable, retrievable.

One chunk = one atomic claim + a hard foreign key home. The employer name and
date range are *denormalized into the chunk* because retrieved chunks get
serialized into a prompt: if the employer isn't in the string, the model has to
guess, and it guesses wrong — a project from Job A lands under Job B, which is
exactly what a background check catches.

`attributed_text()` is the mechanism. Cross-attribution isn't discouraged by a
system prompt, it's structurally unavailable, because every fact arrives
pre-attributed. That costs ~20 tokens per chunk.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field

from .common import Confidence, DateRange


class EntityType(str, Enum):
    EMPLOYMENT_ACHIEVEMENT = "employment_achievement"
    EMPLOYMENT_SUMMARY = "employment_summary"
    PROJECT = "project"
    NOTE = "note"


class Retriever(str, Enum):
    LEXICAL = "lexical"
    DENSE = "dense"
    COMPETENCY_FILTER = "competency_filter"
    FUSED = "fused"


class EvidenceChunk(BaseModel):
    chunk_id: str
    text: str

    # ── Provenance: carried, never inferred ──
    entity_type: EntityType
    entity_id: str = Field(description="Hard FK to the L2 record this came from.")
    employer_id: str | None = None
    employer_name: str | None = Field(
        default=None, description="Denormalized so it CANNOT be lost in the prompt."
    )
    title_at_time: str | None = None
    dates: DateRange = Field(default_factory=DateRange)

    # ── Retrieval keys ──
    competency_tags: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    lexical_terms: list[str] = Field(default_factory=list)
    embedding: list[float] | None = Field(
        default=None, description="None until Phase 1 dense retrieval lands."
    )

    confidence: Confidence = Confidence.PARSED_UNCONFIRMED
    token_count: int = 0
    content_hash: str = ""

    def attributed_text(self) -> str:
        """The only form in which a chunk may enter a prompt."""
        header_parts = [
            self.employer_name or "Personal",
            self.title_at_time,
            self.dates.label() if self.dates.start else None,
        ]
        header = " · ".join(p for p in header_parts if p)
        return f"[{header}]\n{self.text}"

    @staticmethod
    def hash_text(text: str) -> str:
        """Content hash for incremental re-index: edit one bullet, re-embed one chunk."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class RetrievedChunk(BaseModel):
    """A chunk plus why it was selected. This is what the trace viewer renders."""

    chunk_id: str
    score: float
    retriever: Retriever
    source_label: str = Field(description="e.g. 'Acme Corp · Sr Eng · 2021-03 → 2023-06'")
    text_preview: str
    competency_overlap: list[str] = Field(default_factory=list)
    rank_before_rerank: int | None = None


class EvidenceIndex(BaseModel):
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    built_from_ledger_hash: str = ""

    def by_id(self, chunk_id: str) -> EvidenceChunk | None:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def with_competency(self, tags: list[str]) -> list[EvidenceChunk]:
        wanted = set(tags)
        return [c for c in self.chunks if wanted & set(c.competency_tags)]


__all__ = [
    "EntityType",
    "Retriever",
    "EvidenceChunk",
    "RetrievedChunk",
    "EvidenceIndex",
]
