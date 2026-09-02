"""L2 — LEDGER. Append-only typed history: employment, education, projects, credentials.

Corrections never destroy: a wrong record is superseded, not deleted, so the
audit trail survives. Every record here is the *parent* of one or more L3
evidence chunks, and its stable `id` is the foreign key those chunks carry home.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .common import DateRange, Provenance


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    VOLUNTEER = "volunteer"


class LedgerRecord(BaseModel):
    """Base for every append-only record."""

    id: str
    provenance: Provenance
    superseded_by: str | None = Field(
        default=None,
        description="Set when corrected. Superseded records are excluded from retrieval.",
    )

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None


class Achievement(BaseModel):
    """One bullet. Already atomic, so it maps 1:1 to an L3 chunk.

    Chunking by token count would split this across two chunks or merge two
    employers into one. Both failures are silent and both produce fabrication.
    """

    id: str
    text: str
    skill_ids: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(
        default_factory=list, description="Extracted figures, e.g. ['40%', '$1.2M']"
    )


class Employment(LedgerRecord):
    employer: str
    title: str
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    dates: DateRange = Field(default_factory=DateRange)
    location: str | None = None
    summary: str | None = Field(default=None, description="Role context for its achievements.")
    achievements: list[Achievement] = Field(default_factory=list)


class Education(LedgerRecord):
    institution: str
    degree: str
    field_of_study: str | None = None
    dates: DateRange = Field(default_factory=DateRange)
    gpa: float | None = Field(
        default=None,
        description="None is MEANINGFUL — unknown, not zero. Routes to ATTESTATION.",
    )
    honors: list[str] = Field(default_factory=list)


class Project(LedgerRecord):
    name: str
    role: str | None = None
    summary: str | None = None
    dates: DateRange = Field(default_factory=DateRange)
    skill_ids: list[str] = Field(default_factory=list)
    url: str | None = None
    employer_id: str | None = Field(
        default=None,
        description="Parent employment, or None for personal. Attribution matters.",
    )


class Credential(LedgerRecord):
    name: str
    issuer: str
    issued: str | None = None
    expires: str | None = None
    credential_id: str | None = None


class Ledger(BaseModel):
    employment: list[Employment] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    credentials: list[Credential] = Field(default_factory=list)

    def employer_by_id(self, employment_id: str) -> Employment | None:
        return next((e for e in self.employment if e.id == employment_id), None)

    def active_employment(self) -> list[Employment]:
        return [e for e in self.employment if e.is_active]

    def total_years_experience(self) -> float:
        """Computed here, never by the model.

        Embeddings encode `2019` and `2021` almost identically, so any duration
        the LLM derives from retrieved text is unreliable. Resolve it with
        arithmetic and pass the result in as a fact.
        """
        months = 0
        for job in self.active_employment():
            months += _month_span(job.dates)
        return round(months / 12, 1)


def _month_span(dates: DateRange) -> int:
    from datetime import date

    if not dates.start:
        return 0
    try:
        sy, sm = (int(x) for x in dates.start.split("-")[:2])
    except ValueError:
        return 0
    if dates.end:
        try:
            ey, em = (int(x) for x in dates.end.split("-")[:2])
        except ValueError:
            return 0
    else:
        today = date.today()
        ey, em = today.year, today.month
    return max(0, (ey - sy) * 12 + (em - sm))


__all__ = [
    "EmploymentType",
    "LedgerRecord",
    "Achievement",
    "Employment",
    "Education",
    "Project",
    "Credential",
    "Ledger",
]
