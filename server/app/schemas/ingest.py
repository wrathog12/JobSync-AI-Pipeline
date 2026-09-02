"""Ingest — the raw document that enters the pipeline before anything is understood.

This layer produces text and *nothing else*. It makes no claim about what the
text means: no employer, no dates, no skills. Structuring is a separate step
(and an LLM one), because conflating "what characters are on this page" with
"what do they mean" is how a column-scrambling bug turns into a fabricated
employment date that the user then confirms without noticing.

Two failure modes matter far more than the happy path, and both are silent if
you don't look for them:

  * A **scanned PDF** has no text layer. `get_text()` returns "". Without a
    blocking warning that becomes an empty profile the user has to debug.
  * A **two-column résumé** extracts in the wrong reading order, interleaving
    the sidebar into the job history — "Python | 2019-2021 | Acme Corp" — which
    reads plausibly enough to survive a confirmation pass and poison L2.

So a `RawDocument` carries warnings as first-class data, and `is_usable`
fails closed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

#: Below this, the text cannot plausibly be a résumé — it is a cover page, a
#: failed extraction, or the wrong file. Structuring it wastes tokens and
#: produces confident nonsense.
MIN_USABLE_CHARS = 200

#: A résumé is 1-3 pages. Beyond this it is a portfolio, thesis, or the wrong
#: document; not blocking, because some academic CVs really are 12 pages.
TYPICAL_MAX_PAGES = 6


class DocumentKind(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"
    #: Typed or pasted straight into the UI. No extraction, so no layout risk.
    PASTED = "pasted"


class Layout(str, Enum):
    SINGLE_COLUMN = "single_column"
    #: A gutter was detected and the columns were read separately, in order.
    MULTI_COLUMN = "multi_column"
    #: Not a paged format, or too little text to judge.
    UNKNOWN = "unknown"


class WarningCode(str, Enum):
    NO_TEXT_LAYER = "no_text_layer"
    ENCRYPTED = "encrypted"
    TOO_SHORT = "too_short"
    UNSUPPORTED_TYPE = "unsupported_type"
    CORRUPT = "corrupt"
    MULTI_COLUMN = "multi_column"
    MANY_PAGES = "many_pages"
    GARBLED = "garbled"


class ExtractionWarning(BaseModel):
    """A problem worth showing the user, in their words rather than ours."""

    code: WarningCode
    message: str = Field(description="User-facing. Says what to do, not just what broke.")
    blocking: bool = Field(
        default=False,
        description="True => structuring must not run. The text is unusable, not just suspect.",
    )


class RawDocument(BaseModel):
    """Extracted text plus everything we know about how well the extraction went."""

    doc_id: str
    kind: DocumentKind
    filename: str | None = None
    text: str

    page_count: int = Field(default=0, description="0 for non-paged input.")
    layout: Layout = Layout.UNKNOWN
    warnings: list[ExtractionWarning] = Field(default_factory=list)

    sha256: str = Field(
        description="Of the ORIGINAL bytes. Re-uploading the same file is a no-op, "
        "so a user who clicks twice does not get two candidate profiles to reconcile."
    )
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def line_count(self) -> int:
        return len(self.text.splitlines())

    @property
    def is_usable(self) -> bool:
        """Fail closed: any blocking warning stops the pipeline here."""
        return not any(w.blocking for w in self.warnings)

    def blocking_reasons(self) -> list[str]:
        return [w.message for w in self.warnings if w.blocking]

    def advisories(self) -> list[str]:
        """Non-blocking warnings — the user should eyeball the text, not abandon it."""
        return [w.message for w in self.warnings if not w.blocking]


def doc_id_for(digest: str) -> str:
    """Derived from content, not random: the same file always gets the same id."""
    return f"doc_{digest[:16]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "MIN_USABLE_CHARS",
    "TYPICAL_MAX_PAGES",
    "DocumentKind",
    "Layout",
    "WarningCode",
    "ExtractionWarning",
    "RawDocument",
    "doc_id_for",
    "sha256_bytes",
]
