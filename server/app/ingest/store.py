"""Staging area for uploaded documents. Deliberately NOT a memory layer.

A `RawDocument` is not knowledge — it is a pile of characters awaiting
structuring and human confirmation. Keeping it out of `memory/` keeps the L0-L5
boundary honest: text lands here, a human confirms, and only then does anything
reach the durable layers.

Keyed by content hash, so re-uploading the same résumé returns the same document
instead of creating a second candidate profile to reconcile.

PHASE 1 TASK: once structuring lands, each document gains a candidate record set
hanging off it, and the confirmation pass reads from here.
"""

from __future__ import annotations

from ..schemas.ingest import RawDocument

#: Small on purpose. A user uploads a résumé, maybe a cover letter, maybe a
#: corrected re-export. Nobody needs fifty.
MAX_DOCUMENTS = 20


class DocumentStore:
    def __init__(self) -> None:
        self._docs: dict[str, RawDocument] = {}

    def put(self, doc: RawDocument) -> RawDocument:
        """Idempotent: the same bytes always return the first extraction.

        Returns the STORED document, which may be the earlier one — so a double
        click on upload cannot fork the ingest flow.
        """
        existing = self._docs.get(doc.doc_id)
        if existing is not None:
            return existing
        self._docs[doc.doc_id] = doc
        self._evict()
        return doc

    def get(self, doc_id: str | None) -> RawDocument | None:
        return self._docs.get(doc_id) if doc_id else None

    def all(self) -> list[RawDocument]:
        return sorted(self._docs.values(), key=lambda d: d.extracted_at, reverse=True)

    def usable(self) -> list[RawDocument]:
        """The ones structuring may actually run on."""
        return [d for d in self.all() if d.is_usable]

    def drop(self, doc_id: str) -> bool:
        return self._docs.pop(doc_id, None) is not None

    def clear(self) -> None:
        self._docs.clear()

    def _evict(self) -> None:
        for doc in self.all()[MAX_DOCUMENTS:]:
            self._docs.pop(doc.doc_id, None)


DOCUMENTS = DocumentStore()


def get_documents() -> DocumentStore:
    return DOCUMENTS


__all__ = ["MAX_DOCUMENTS", "DocumentStore", "DOCUMENTS", "get_documents"]
