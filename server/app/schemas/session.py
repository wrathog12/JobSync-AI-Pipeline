"""L6 — the application session. One live application, spanning many pages.

This is the layer that makes a multi-page wizard work. Everything in L0-L5 is
DURABLE and describes the person; L6 is DISPOSABLE and describes one attempt at
one job. The boundary between them is the most important rule in the file:

    Nothing in a session writes to L0-L5 without explicit user approval.

Without that, a single AGGRESSIVE-mode application permanently contaminates the
durable profile, and every future application inherits the exaggeration. L5 is
"earned from approvals" precisely so this cannot happen by accident.

Why a session exists at all — four things a per-field function cannot do:

    1. ANTI-REPETITION. The loudest tell of an auto-filled application is the
       same STAR story answering "leadership", then "conflict", then "failure".
       `spent_chunks` lets retrieval penalise evidence already used.
    2. CONSISTENCY. Page 1 "why this role" and page 6 "what interests you about
       the team" must tell one story. Reviewers read the packet whole.
    3. STRETCH COHERENCE. A claim stretched on page 2 must be carried by the
       resume and cover letter, not re-stretched differently.
    4. IDEMPOTENCE. Wizards have a back button. Re-encountering a field must
       return the same answer, not regenerate a different one.

Lifetime: created when the user opens an application, lives in the extension's
background service worker (NOT the content script — page navigation destroys
content-script state, which is exactly the multi-page case), discarded on
submit unless the user promotes answers into L5.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .common import GenerationMode
from .trace import ClaimStretch

#: How much a chunk's relevance is multiplied by once it has been used in this
#: session. Not zero: sometimes a story genuinely is the best answer to two
#: questions, and an outright ban would force a worse answer or a false
#: abstention. A penalty lets strong evidence win twice while giving anything
#: comparable the edge.
#:
#: PHASE 1 TASK: this is a guess, like RELEVANCE_FLOOR. It needs the same
#: treatment — a multi-question eval where repetition is scored.
SPENT_CHUNK_PENALTY = 0.55

#: Below this, a penalised chunk is dropped rather than merely demoted, so a
#: thrice-used chunk cannot keep crowding out fresh evidence.
SPENT_CHUNK_DROP_AFTER = 2


class AnsweredField(BaseModel):
    """One field this session has already answered, keyed for idempotent replay."""

    field_key: str = Field(
        description="Stable identity of the field across page reloads. See `field_key()`."
    )
    question: str
    answer: str | None = None
    abstained: bool = False
    mode: GenerationMode
    trace_id: str
    used_chunks: list[str] = Field(default_factory=list)
    page_index: int = 0
    approved_by_user: bool = Field(
        default=False,
        description="Only an approved answer may ever be promoted into L5.",
    )
    answered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApplicationSession(BaseModel):
    """L6. Scratch space for one application. Never a source of truth about the user."""

    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    company: str | None = None
    role_title: str | None = None
    origin: str | None = Field(
        default=None, description="e.g. 'company.wd5.myworkdayjobs.com' — part of the session key."
    )

    #: Retained once, reused on every page. The whole reason a session beats
    #: re-reading the page: by page 4 of a Workday wizard the JD is long gone
    #: from the DOM.
    jd_text: str | None = None
    jd_fingerprint: str | None = None

    mode: GenerationMode = GenerationMode.STRICT
    page_index: int = 0
    pages_seen: list[str] = Field(default_factory=list)

    answered: list[AnsweredField] = Field(default_factory=list)

    #: chunk_id -> times used. The anti-repetition ledger.
    spent_chunks: dict[str, int] = Field(default_factory=dict)

    #: Every stretch made anywhere in this application, so the resume and cover
    #: letter can carry exactly the same ones.
    stretches: list[ClaimStretch] = Field(default_factory=list)

    # ── reads ──────────────────────────────────────────────────────────────────

    def prior(self, field_key: str) -> AnsweredField | None:
        """The back-button case: same field, same answer, zero tokens."""
        return next((a for a in self.answered if a.field_key == field_key), None)

    def spend_multiplier(self, chunk_id: str) -> float:
        """Relevance multiplier for a chunk given how often this session used it."""
        used = self.spent_chunks.get(chunk_id, 0)
        return 1.0 if used == 0 else SPENT_CHUNK_PENALTY**used

    def is_exhausted(self, chunk_id: str) -> bool:
        return self.spent_chunks.get(chunk_id, 0) >= SPENT_CHUNK_DROP_AFTER

    def answered_questions(self) -> list[str]:
        """Prior questions and answers, for the consistency section of a prompt."""
        return [a.question for a in self.answered if a.answer]

    def consistency_context(self, limit: int = 4, max_chars: int = 900) -> str | None:
        """What this session has already claimed, condensed for a prompt.

        Deliberately capped. The point is to keep one story straight, not to
        replay the whole application into every prompt — that grows cost
        linearly with page count and buries the actual question.
        """
        prior = [a for a in reversed(self.answered) if a.answer][:limit]
        if not prior:
            return None
        lines = []
        for a in prior:
            snippet = a.answer or ""
            if len(snippet) > 220:
                snippet = snippet[:220].rsplit(" ", 1)[0] + "…"
            lines.append(f"Q: {a.question}\nA: {snippet}")
        out = "\n\n".join(lines)
        return out[:max_chars]

    # ── writes ─────────────────────────────────────────────────────────────────

    def set_jd(self, jd_text: str | None) -> None:
        self.jd_text = jd_text or None
        self.jd_fingerprint = jd_fingerprint(jd_text) if jd_text else None

    def record(self, entry: AnsweredField, stretches: list[ClaimStretch] | None = None) -> None:
        """Commit one answered field. Replaces any prior answer for the same key."""
        self.answered = [a for a in self.answered if a.field_key != entry.field_key]
        self.answered.append(entry)
        for cid in entry.used_chunks:
            self.spent_chunks[cid] = self.spent_chunks.get(cid, 0) + 1
        for s in stretches or []:
            if not any(x.claim == s.claim for x in self.stretches):
                self.stretches.append(s)

    def advance_page(self, page_url: str | None = None) -> None:
        self.page_index += 1
        if page_url:
            self.pages_seen.append(page_url)


# ── keys ───────────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def field_key(question: str, field_type: str = "textarea") -> str:
    """Stable identity for a field across page reloads and re-renders.

    Deliberately NOT the DOM id: Workday regenerates ids on every render, so an
    id-keyed cache would miss on the back button — the exact case it exists for.
    The normalised question text is the one thing that survives.
    """
    norm = _WS.sub(" ", question.strip().lower())
    return f"fk_{hashlib.sha1(f'{field_type}|{norm}'.encode()).hexdigest()[:16]}"


def jd_fingerprint(jd_text: str) -> str:
    """Identifies the JD so a session survives navigation without trusting the URL.

    Workday's URL changes on every wizard step, so the URL cannot key a session.
    The JD text is stable for the duration of one application.
    """
    norm = _WS.sub(" ", jd_text.strip().lower())
    return f"jd_{hashlib.sha1(norm.encode()).hexdigest()[:12]}"


__all__ = [
    "AnsweredField",
    "ApplicationSession",
    "field_key",
    "jd_fingerprint",
    "SPENT_CHUNK_PENALTY",
    "SPENT_CHUNK_DROP_AFTER",
]
