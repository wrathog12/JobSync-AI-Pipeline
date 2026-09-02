"""Derivation: L2 Ledger -> L3 Evidence -> L4 Competency Graph.

Both derived layers are droppable. `DELETE L3, L4 -> rebuild from L2` has to be
a routine operation, not a scary one — that's what lets us change the chunking
strategy or swap embedding models later without data loss. L5 answer memory
survives every rebuild because it's keyed by question, not by chunk.

Chunking is by MEANING, not token count: one achievement bullet = one chunk.
"""

from __future__ import annotations

import re

from ..schemas.competency import (
    CompetencyGraph,
    CompetencyNode,
    Proficiency,
    SkillKind,
    SkillNode,
)
from ..schemas.evidence import EntityType, EvidenceChunk, EvidenceIndex
from ..schemas.ledger import Ledger
from ..taxonomy import competencies as comp_tax

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+.#-]*")

#: Stopwords for BM25 indexing and querying.
#:
#: Includes question boilerplate ("tell", "us", "describe", "example", "time"),
#: because a behavioural question is mostly boilerplate and leaving it in makes
#: BM25 rank on it. Before this, "tell us about a TIME something went wrong"
#: matched a chunk about reducing release TIME — the single worst chunk available.
#:
#: Not the same set as `canonical_questions.QUESTION_NOISE`, which normalizes
#: phrasing for alias lookup rather than indexing evidence.
STOPWORDS = frozenset(
    """a an and are as at be by for from had has have in into is it its of on or that the
    to was were will with which who whom this these those i my me we our you your they
    their he she his her them then than so such but not no nor if while during across
    tell us describe explain share provide give please kindly briefly about anything
    something time when what how why example experience your you role position
    situation instance occasion""".split()
)


def lexical_terms(text: str) -> list[str]:
    """Terms for BM25. Keeps `p99`, `c++`, `.net`, `node.js` intact."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


_METRIC_RE = re.compile(r"(\$?\d[\d,.]*\s*(?:%|k|m|bn|b|x|ms|s|gb|tb|users|customers)?)", re.I)


def extract_metrics(text: str) -> list[str]:
    return [m.strip() for m in _METRIC_RE.findall(text) if any(c.isdigit() for c in m)]


# ── L2 -> L3 ───────────────────────────────────────────────────────────────────


def build_evidence_index(ledger: Ledger) -> EvidenceIndex:
    chunks: list[EvidenceChunk] = []

    for job in ledger.active_employment():
        if job.summary:
            chunks.append(
                _chunk(
                    chunk_id=f"ch_{job.id}_summary",
                    text=job.summary,
                    entity_type=EntityType.EMPLOYMENT_SUMMARY,
                    entity_id=job.id,
                    employer_id=job.id,
                    employer_name=job.employer,
                    title=job.title,
                    dates=job.dates,
                    confidence=job.provenance.confidence,
                )
            )
        for ach in job.achievements:
            chunks.append(
                _chunk(
                    chunk_id=f"ch_{ach.id}",
                    text=ach.text,
                    entity_type=EntityType.EMPLOYMENT_ACHIEVEMENT,
                    entity_id=ach.id,
                    employer_id=job.id,
                    employer_name=job.employer,
                    title=job.title,
                    dates=job.dates,
                    confidence=job.provenance.confidence,
                    skill_ids=ach.skill_ids,
                    metrics=ach.metrics,
                )
            )

    for prj in ledger.projects:
        if not prj.is_active or not prj.summary:
            continue
        parent = ledger.employer_by_id(prj.employer_id) if prj.employer_id else None
        chunks.append(
            _chunk(
                chunk_id=f"ch_{prj.id}",
                text=f"{prj.name}: {prj.summary}",
                entity_type=EntityType.PROJECT,
                entity_id=prj.id,
                employer_id=prj.employer_id,
                # Personal projects must NOT borrow an employer's name.
                employer_name=parent.employer if parent else None,
                title=prj.role,
                dates=prj.dates,
                confidence=prj.provenance.confidence,
                skill_ids=prj.skill_ids,
            )
        )

    # Education and skills are deliberately NOT chunked: they're structured
    # records answered by key lookup. Embedding them destroys the structure and
    # invites negation collapse ("no production Kubernetes" ~= "production
    # Kubernetes" in embedding space).
    return EvidenceIndex(chunks=chunks)


def _chunk(
    *,
    chunk_id: str,
    text: str,
    entity_type: EntityType,
    entity_id: str,
    employer_id: str | None,
    employer_name: str | None,
    title: str | None,
    dates,
    confidence,
    skill_ids: list[str] | None = None,
    metrics: list[str] | None = None,
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        text=text,
        entity_type=entity_type,
        entity_id=entity_id,
        employer_id=employer_id,
        employer_name=employer_name,
        title_at_time=title,
        dates=dates,
        skill_ids=skill_ids or [],
        metrics=metrics or extract_metrics(text),
        lexical_terms=lexical_terms(text),
        competency_tags=infer_competency_tags(text),
        confidence=confidence,
        token_count=approx_tokens(text),
        content_hash=EvidenceChunk.hash_text(text),
    )


#: Phase 0 stand-in for the ingest-time LLM tagger. Keyword-based, deliberately
#: crude — it exists so the trace viewer shows real tag overlap end to end. The
#: real tagger is one cached LLM pass per chunk in Phase 1.
_TAG_HINTS: dict[str, tuple[str, ...]] = {
    "leadership": ("led", "managed", "headed", "directed", "ran a team"),
    "mentorship": ("mentored", "coached", "onboarded", "trained", "taught"),
    "influence_without_authority": ("convinced", "persuaded", "aligned", "buy-in", "advocated",
                                    "cross-team", "cross-functional"),
    "conflict_resolution": ("resolved", "mediated", "disagreement", "conflict"),
    "ambiguity": ("ambiguous", "undefined", "greenfield", "from scratch", "no clear"),
    "technical_depth": ("architected", "optimized", "refactored", "debugged", "latency",
                        "throughput", "algorithm", "kernel", "query"),
    "technical_breadth": ("full-stack", "end-to-end", "across the stack"),
    "failure_and_learning": ("postmortem", "incident", "outage", "regression", "learned"),
    "ownership": ("owned", "end-to-end", "shipped", "drove", "delivered"),
    "customer_focus": ("customer", "user research", "user feedback", "nps", "churn"),
    "scale": ("scaled", "million", "billion", "qps", "rps", "high traffic", "concurrent"),
    "process_improvement": ("automated", "streamlined", "reduced toil", "ci/cd", "workflow"),
    "collaboration": ("partnered", "collaborated", "worked with", "paired"),
    "communication": ("presented", "documented", "wrote", "spoke", "briefed"),
    "prioritization": ("prioritized", "deprioritized", "roadmap", "triaged", "scoped"),
    "data_driven": ("a/b", "experiment", "metrics", "instrumented", "measured", "analytics"),
    "innovation": ("prototyped", "invented", "first", "novel", "patent"),
    "reliability": ("uptime", "sla", "slo", "p99", "flaky", "stability", "error rate"),
    "cost_efficiency": ("cost", "spend", "savings", "reduced spend", "cheaper"),
    "stakeholder_management": ("stakeholder", "executive", "leadership team", "vp", "c-level"),
}


def infer_competency_tags(text: str) -> list[str]:
    low = text.lower()
    tags = [tag for tag, hints in _TAG_HINTS.items() if any(h in low for h in hints)]
    return sorted(t for t in tags if comp_tax.is_valid(t))


# ── L3 -> L4 ───────────────────────────────────────────────────────────────────


def build_competency_graph(
    ledger: Ledger, index: EvidenceIndex, declared_skills: list[SkillNode] | None = None
) -> CompetencyGraph:
    """Aggregate tags upward. Soft skills get counts, never checkmarks."""
    skills: dict[str, SkillNode] = {s.id: s.model_copy(deep=True) for s in (declared_skills or [])}

    # Back every declared skill with the chunks that actually reference it.
    for chunk in index.chunks:
        for sid in chunk.skill_ids:
            node = skills.get(sid)
            if node is None:
                node = SkillNode(id=sid, name=sid.removeprefix("sk_").replace("_", " ").title())
                skills[sid] = node
            if chunk.chunk_id not in node.evidence_ids:
                node.evidence_ids.append(chunk.chunk_id)
            if chunk.dates.end is None:
                node.last_used = "present"
            elif node.last_used != "present":
                node.last_used = max(node.last_used or "", chunk.dates.end)

    for node in skills.values():
        if node.proficiency is None and node.is_backed:
            node.proficiency = (
                Proficiency.ADVANCED if len(node.evidence_ids) >= 3 else Proficiency.WORKING
            )

    # Every competency in the taxonomy gets a node, INCLUDING zero-evidence ones.
    # The empties are the product: they're what we abstain on and then ask about.
    competencies: list[CompetencyNode] = []
    for tag, label in comp_tax.COMPETENCIES.items():
        backing = [c.chunk_id for c in index.chunks if tag in c.competency_tags]
        strongest = max(
            (c for c in index.chunks if tag in c.competency_tags),
            key=lambda c: (len(c.metrics), c.token_count),
            default=None,
        )
        competencies.append(
            CompetencyNode(
                tag=tag,
                label=label,
                evidence_ids=backing,
                strongest_chunk_id=strongest.chunk_id if strongest else None,
            )
        )

    for s in skills.values():
        if s.kind == SkillKind.SOFT:
            # A soft skill may never live in the skills list as a bare claim.
            s.kind = SkillKind.SOFT
            s.proficiency = None

    return CompetencyGraph(
        skills=sorted(skills.values(), key=lambda s: s.name.lower()),
        competencies=competencies,
    )


__all__ = [
    "lexical_terms",
    "approx_tokens",
    "extract_metrics",
    "infer_competency_tags",
    "build_evidence_index",
    "build_competency_graph",
]
