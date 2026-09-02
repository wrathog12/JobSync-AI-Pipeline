"""BM25 over the evidence index, plus the VectorIndex seam for dense later.

Lexical first is deliberate and slightly counter-intuitive. This corpus is dense
in proper nouns — Kubernetes, PostgreSQL, CPA, Series 7, company names, degree
names — which is exactly where embeddings are weakest and BM25 is exact. It needs
no model download, no ingest-time inference, and no vector storage.

Add dense only where a labelled eval set proves BM25 missed.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

from ..memory.derive import lexical_terms
from ..schemas.evidence import EvidenceChunk

K1 = 1.5
B = 0.75


class BM25Index:
    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self.chunks = chunks
        self.doc_terms: list[Counter[str]] = [Counter(c.lexical_terms) for c in chunks]
        self.doc_len = [sum(t.values()) for t in self.doc_terms]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0

        self.df: Counter[str] = Counter()
        for terms in self.doc_terms:
            self.df.update(terms.keys())
        self.n = len(chunks)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        q_terms = lexical_terms(query)
        if not q_terms or self.n == 0:
            return []

        scored: list[tuple[str, float]] = []
        for i, chunk in enumerate(self.chunks):
            terms = self.doc_terms[i]
            length = self.doc_len[i] or 1
            score = 0.0
            for t in q_terms:
                tf = terms.get(t, 0)
                if tf == 0:
                    continue
                denom = tf + K1 * (1 - B + B * length / (self.avg_len or 1))
                score += self._idf(t) * (tf * (K1 + 1)) / denom
            if score > 0:
                scored.append((chunk.chunk_id, round(score, 4)))

        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:k]


class VectorIndex(Protocol):
    """The seam that makes the HNSW question a one-day decision instead of an
    architectural one.

    Phase 1 ships `FlatIndex`: exact cosine over a Float32Array, 1-3 ms at
    N=2,000, 100% recall. HNSW drops in behind this same interface if a single
    user's corpus ever passes ~50k chunks — which it won't, because retrieval is
    scoped to one user for privacy reasons, so N never grows with user count.
    """

    def add(self, chunk_id: str, vec: list[float]) -> None: ...
    def remove(self, chunk_id: str) -> None: ...
    def search(self, query: list[float], k: int) -> list[tuple[str, float]]: ...


class FlatIndex:
    """Exact brute-force cosine. Not approximate, so it cannot miss the user's
    single best achievement — which an ANN index at this N genuinely can."""

    def __init__(self) -> None:
        self._vecs: dict[str, list[float]] = {}

    def add(self, chunk_id: str, vec: list[float]) -> None:
        self._vecs[chunk_id] = vec

    def remove(self, chunk_id: str) -> None:
        self._vecs.pop(chunk_id, None)

    def search(self, query: list[float], k: int) -> list[tuple[str, float]]:
        qn = math.sqrt(sum(x * x for x in query)) or 1.0
        out: list[tuple[str, float]] = []
        for cid, vec in self._vecs.items():
            dot = sum(a * b for a, b in zip(query, vec))
            vn = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append((cid, dot / (qn * vn)))
        out.sort(key=lambda p: p[1], reverse=True)
        return out[:k]


#: BM25 scores are unbounded, which makes an absolute relevance floor
#: uninterpretable. Squash to 0..1 monotonically so the gate threshold and the
#: number shown in the trace viewer mean the same thing.
SATURATION_K = 3.0


def normalize_score(bm25: float, k: float = SATURATION_K) -> float:
    """bm25 -> 0..1. At bm25 == k the result is 0.5."""
    if bm25 <= 0:
        return 0.0
    return round(bm25 / (bm25 + k), 4)


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]], k: int = 60
) -> list[tuple[str, float]]:
    """RRF needs no score normalization across retrievers, so there are no
    dense/sparse weights to hand-tune. Use it instead of tuning."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (cid, _score) in enumerate(ranking, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    out = sorted(fused.items(), key=lambda p: p[1], reverse=True)
    return [(cid, round(s, 6)) for cid, s in out]


__all__ = ["BM25Index", "VectorIndex", "FlatIndex", "reciprocal_rank_fusion"]
