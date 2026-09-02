"""Shared enums, provenance, and the mode policy every other layer depends on.

This module is the root of the schema DAG. Nothing here imports from a layer.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── Trust ──────────────────────────────────────────────────────────────────────


class Confidence(str, Enum):
    """How much we trust a stored fact.

    `PARSED_UNCONFIRMED` data must never reach a DETERMINISTIC fill or an
    ATTESTATION decision — it has not passed the human confirmation pass yet.
    """

    VERIFIED = "verified"
    USER_STATED = "user_stated"
    PARSED_UNCONFIRMED = "parsed_unconfirmed"


class Source(str, Enum):
    USER_ENTERED = "user_entered"
    PARSED_RESUME = "parsed_resume"
    PARSED_LINKEDIN = "parsed_linkedin"
    DERIVED = "derived"


class Provenance(BaseModel):
    """Attached to every authored record. Derived layers carry their parent's."""

    confidence: Confidence
    source: Source
    confirmed_at: datetime | None = Field(
        default=None,
        description="Set only by the human confirmation pass. None => never confirmed.",
    )
    updated_at: datetime | None = None

    @property
    def is_confirmed(self) -> bool:
        """A human has signed off on this value.

        Deliberately not `confidence == VERIFIED`. A user clicking "yes, that's
        right" produces `USER_STATED`, and requiring VERIFIED here would mark
        everything they typed themselves as unconfirmed and block it from the
        DETERMINISTIC path forever. VERIFIED stays reserved for a fact checked
        against something external — a payslip, a transcript — which is worth
        keeping expressible rather than spending on a button click.
        """
        return self.confidence != Confidence.PARSED_UNCONFIRMED and self.confirmed_at is not None


# ── Generation modes ───────────────────────────────────────────────────────────


class GenerationMode(str, Enum):
    """The single knob that separates grounded output from embellished output.

    Modes do not change what is stored, only how far a generated claim may
    travel from its backing evidence. See `MODE_MAX_CLAIM_DISTANCE`.
    """

    STRICT = "strict"
    OPTIMIZE = "optimize"
    AGGRESSIVE = "aggressive"


MODE_MAX_CLAIM_DISTANCE: dict[GenerationMode, float] = {
    GenerationMode.STRICT: 0.0,
    GenerationMode.OPTIMIZE: 0.30,
    GenerationMode.AGGRESSIVE: 0.70,
}

MODE_DESCRIPTION: dict[GenerationMode, str] = {
    GenerationMode.STRICT: "Only claims with direct backing evidence. Nothing inferred.",
    GenerationMode.OPTIMIZE: (
        "Reframes real evidence in the job description's vocabulary. Reorders and "
        "reweights. Introduces no new facts."
    ),
    GenerationMode.AGGRESSIVE: (
        "Claims adjacent and transferable skills, inflates scope and proficiency. "
        "Every stretched claim is recorded with what it stretched from."
    ),
}


# ── Mode-immune facts ──────────────────────────────────────────────────────────

#: Dotted paths that stay grounded in EVERY mode, including AGGRESSIVE.
#:
#: These are the facts a background check verifies. Inflating them is fraud
#: rather than salesmanship, and the cost lands on the user after they have
#: already accepted an offer. Skills, scope, and impact framing are fair game;
#: these are not.
MODE_IMMUNE_PATHS: frozenset[str] = frozenset(
    {
        "identity.legal_first",
        "identity.legal_middle",
        "identity.legal_last",
        "identity.date_of_birth",
        "identity.citizenship",
        "profile.authorization",
        "ledger.education.degree",
        "ledger.education.institution",
        "ledger.education.start",
        "ledger.education.end",
        "ledger.education.gpa",
        "ledger.employment.employer",
        "ledger.employment.title",
        "ledger.employment.start",
        "ledger.employment.end",
        "ledger.credentials",
    }
)


def is_mode_immune(path: str) -> bool:
    """True if `path` (or any ancestor of it) is pinned to strict grounding."""
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in MODE_IMMUNE_PATHS:
            return True
    return False


# ── Small shared value objects ─────────────────────────────────────────────────


class DateRange(BaseModel):
    """`end is None` means current. Drives recency ranking, so never omit it."""

    start: str | None = Field(default=None, description="YYYY-MM, normalized at ingest")
    end: str | None = Field(default=None, description="YYYY-MM, or None for current")

    @property
    def is_current(self) -> bool:
        return self.end is None

    def label(self) -> str:
        if not self.start:
            return "date unknown"
        return f"{self.start} → {self.end or 'present'}"


class Money(BaseModel):
    amount: float
    currency: str = "USD"
    basis: str = "annual"


__all__ = [
    "Confidence",
    "Source",
    "Provenance",
    "GenerationMode",
    "MODE_MAX_CLAIM_DISTANCE",
    "MODE_DESCRIPTION",
    "MODE_IMMUNE_PATHS",
    "is_mode_immune",
    "DateRange",
    "Money",
    "date",
    "datetime",
]
