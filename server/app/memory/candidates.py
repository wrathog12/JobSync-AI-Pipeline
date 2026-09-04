"""Staging for structuring output, before any of it is memory.

Deliberately separate from `MemoryStore`, and deliberately authoritative.

Authoritative matters more than it looks. The confirmation pass has to tell two
things apart: a bullet the user *edited* (their own words, legitimate evidence)
and a bullet they *rubber-stamped* unchanged that the model had invented. The only
way to know which is which is to compare what comes back against what the model
actually produced — so the original has to be held somewhere the client cannot
rewrite. That is this.

Same lifecycle as `DocumentStore`: in-process, bounded, disposable.
"""

from __future__ import annotations

from ..schemas.structured import StructureResult

MAX_CANDIDATES = 20


class CandidateStore:
    def __init__(self) -> None:
        self._by_doc: dict[str, StructureResult] = {}

    def put(self, result: StructureResult) -> StructureResult:
        """Latest wins, unlike documents.

        Re-structuring a document is a deliberate retry — a prompt change, a
        different model — and the newer reading is the one the user is looking at.
        """
        self._by_doc[result.doc_id] = result
        self._evict()
        return result

    def get(self, doc_id: str) -> StructureResult | None:
        return self._by_doc.get(doc_id)

    def all(self) -> list[StructureResult]:
        return list(self._by_doc.values())

    def drop(self, doc_id: str) -> bool:
        return self._by_doc.pop(doc_id, None) is not None

    def clear(self) -> None:
        self._by_doc.clear()

    def _evict(self) -> None:
        while len(self._by_doc) > MAX_CANDIDATES:
            self._by_doc.pop(next(iter(self._by_doc)))


CANDIDATES = CandidateStore()


def get_candidates() -> CandidateStore:
    return CANDIDATES


__all__ = ["CandidateStore", "CANDIDATES", "get_candidates", "MAX_CANDIDATES"]
