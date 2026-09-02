"""The structuring contract: what the model is allowed to emit from a document.

These `Candidate*` models are deliberately **not** the L0/L1/L2 storage models,
even though they carry nearly the same fields. Three things the model must not
control, and the only reliable way to enforce that is to leave them out of the
schema entirely:

* **`provenance`.** Everything extracted here is `PARSED_UNCONFIRMED` /
  `PARSED_RESUME`, stamped by code. If the model could emit a `Confidence`, it
  could emit `VERIFIED`, and unconfirmed data would reach the DETERMINISTIC fill
  path — the exact contamination the confirmation pass exists to prevent.
* **`id`.** Ours to mint, deterministically from the document, so re-structuring
  the same file twice produces the same records instead of duplicates.
* **work authorization.** `WorkAuthorization` is pinned to `USER_ENTERED` for a
  reason: a résumé showing US employment does not imply US work authorization.
  There is no field here to write it into, so no prompt change can start
  inferring it. If the document *mentions* sponsorship we raise a warning telling
  the user to enter it by hand, which is the honest version of helpful.

The other thing this file encodes is that **achievement text must be verbatim**.
L3 evidence chunks come from these bullets, and the grounding check compares
generated prose against them. If the structurer paraphrases, the "evidence" is
already model prose and grounding becomes a check of one generation against
another — reassuring and worthless. `structure.py` verifies each quote against
the source and flags the ones it cannot find.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .common import DateRange, Provenance
from .identity import Identity
from .ledger import EmploymentType, Ledger
from .profile import Profile

# ── what the model emits ───────────────────────────────────────────────────────


class CandidateName(BaseModel):
    """Split rather than one string, because "de la Cruz" and "Van Der Berg" break
    every naive last-token split, and the model has the context to get it right."""

    legal_first: str
    legal_middle: str | None = None
    legal_last: str
    preferred_name: str | None = Field(
        default=None,
        description=(
            "Only if the document shows a different everyday name, e.g. a nickname "
            "in quotes or parentheses. Never a guess or a shortening you invented."
        ),
    )


class CandidateContact(BaseModel):
    email: str | None = None
    phone: str | None = Field(
        default=None, description="Exactly as written. Do not reformat or add a country code."
    )
    city: str | None = None
    region: str | None = Field(default=None, description="State, province, or region.")
    country: str | None = None
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = Field(
        default=None, description="Personal site or portfolio. Not a social profile."
    )
    other_urls: list[str] = Field(default_factory=list)


class CandidateAchievement(BaseModel):
    """One bullet, copied verbatim.

    The verbatim rule is not stylistic. This text becomes an evidence chunk that
    the grounding check treats as ground truth, so a paraphrase here launders a
    model claim into a fact about the user's career.
    """

    text: str = Field(
        description=(
            "The bullet copied EXACTLY from the document, character for character. "
            "Do not rewrite, shorten, expand, fix grammar, or merge two bullets. "
            "Strip only the leading bullet glyph."
        )
    )


class CandidateEmployment(BaseModel):
    employer: str
    title: str
    employment_type: EmploymentType | None = Field(
        default=None, description="Only if the document says so. Do not infer from the title."
    )
    start: str | None = Field(default=None, description="YYYY-MM, or YYYY if no month is given.")
    end: str | None = Field(
        default=None, description="YYYY-MM, or null if this is the current role."
    )
    is_current: bool = Field(
        default=False,
        description=(
            "True only if the document says so ('Present', 'Current'). This is asked "
            "separately from `end` because a missing end date and an ongoing role are "
            "different facts."
        ),
    )
    location: str | None = None
    summary: str | None = Field(
        default=None,
        description="Role-level context if the document has a paragraph for it. Not a summary you wrote.",
    )
    achievements: list[CandidateAchievement] = Field(default_factory=list)


class CandidateEducation(BaseModel):
    institution: str
    degree: str = Field(description="As written, e.g. 'B.S.', 'Bachelor of Science', 'MBA'.")
    field_of_study: str | None = None
    start: str | None = None
    end: str | None = Field(default=None, description="Graduation date. YYYY-MM or YYYY.")
    gpa: float | None = Field(
        default=None,
        description=(
            "Only if stated as a number. Null means not stated — which is a real "
            "answer we must be able to give, so never estimate it."
        ),
    )
    honors: list[str] = Field(default_factory=list)


class CandidateProject(BaseModel):
    name: str
    role: str | None = None
    summary: str | None = Field(
        default=None, description="The project's description as written, not your own."
    )
    start: str | None = None
    end: str | None = None
    url: str | None = None
    employer: str | None = Field(
        default=None,
        description=(
            "The employer this was built at, matching an `employer` above exactly, or "
            "null for personal and academic work. Attribution matters: claiming a "
            "personal project as employer work is a checkable lie."
        ),
    )
    technologies: list[str] = Field(default_factory=list)


class CandidateCredential(BaseModel):
    name: str
    issuer: str
    issued: str | None = None
    expires: str | None = None
    credential_id: str | None = None


class ExtractedDocument(BaseModel):
    """The single schema the structuring call requests.

    One call rather than one per section: an employer's bullets, the project that
    belongs to that employer, and the skill list that the bullets justify are all
    the same reading of the same page. Splitting the call throws that context away
    and then needs a reconciliation step to get it back.
    """

    name: CandidateName | None = Field(
        default=None, description="Null only if the document genuinely has no name on it."
    )
    contact: CandidateContact = Field(default_factory=CandidateContact)
    headline: str | None = Field(
        default=None, description="A title line like 'Senior Backend Engineer', if present."
    )
    summary: str | None = Field(
        default=None, description="The document's own summary or objective paragraph, verbatim."
    )
    employment: list[CandidateEmployment] = Field(default_factory=list)
    education: list[CandidateEducation] = Field(default_factory=list)
    projects: list[CandidateProject] = Field(default_factory=list)
    credentials: list[CandidateCredential] = Field(default_factory=list)
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skills the document names explicitly, including from a skills section. "
            "These are DECLARED, not demonstrated — the graph flags any skill no "
            "achievement backs, so listing one the bullets do not support is visible."
        ),
    )
    mentions_work_authorization: bool = Field(
        default=False,
        description=(
            "True if the document says anything about visa status, sponsorship, or "
            "work eligibility. Do NOT extract what it says — flag it only, so the "
            "user can enter it themselves."
        ),
    )
    languages: list[str] = Field(default_factory=list)


# ── what we produce from it ────────────────────────────────────────────────────


class StructureWarningCode(str, Enum):
    QUOTE_NOT_FOUND = "quote_not_found"
    """An achievement is not present in the source text. Either the model
    paraphrased it or invented it; both are disqualifying for evidence."""
    DATE_UNPARSEABLE = "date_unparseable"
    DATE_IMPRECISE = "date_imprecise"
    """Year with no month. Normalized to a month so duration maths still works,
    which means the exact figure is an approximation the user should check."""
    DATE_REVERSED = "date_reversed"
    NO_NAME = "no_name"
    NO_EMPLOYMENT = "no_employment"
    """Suspicious for a résumé — usually a layout the extractor mangled."""
    MULTIPLE_CURRENT = "multiple_current"
    AUTHORIZATION_MENTIONED = "authorization_mentioned"
    UNKNOWN_PROJECT_EMPLOYER = "unknown_project_employer"
    """The model attributed a project to an employer it did not also list, so the
    attribution cannot be trusted. Demoted to personal rather than guessed at."""
    TRUNCATED = "truncated"


class StructureWarning(BaseModel):
    code: StructureWarningCode
    message: str
    """User-facing. Says what to check, not just what happened."""
    record_id: str | None = None
    """Which record it concerns, so the confirmation UI can point at it."""


class StructureResult(BaseModel):
    """Candidate memory, built but not committed.

    Returns real `Identity` / `Profile` / `Ledger` objects at
    `PARSED_UNCONFIRMED` so the confirmation pass has nothing left to translate —
    it confirms and commits. Nothing here has touched the store.
    """

    doc_id: str
    identity: Identity | None = None
    profile: Profile | None = None
    ledger: Ledger = Field(default_factory=Ledger)
    skills: list[str] = Field(default_factory=list)
    headline: str | None = None
    summary: str | None = None
    languages: list[str] = Field(default_factory=list)
    warnings: list[StructureWarning] = Field(default_factory=list)

    model: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    ms: int = 0

    @property
    def record_count(self) -> int:
        led = self.ledger
        return (
            len(led.employment) + len(led.education) + len(led.projects) + len(led.credentials)
        )

    @property
    def achievement_count(self) -> int:
        return sum(len(e.achievements) for e in self.ledger.employment)

    @property
    def unverified_quotes(self) -> int:
        """Achievements we could not find in the source. Non-zero means the
        evidence index would be built on model prose."""
        return sum(1 for w in self.warnings if w.code == StructureWarningCode.QUOTE_NOT_FOUND)

    def blocking(self) -> list[StructureWarning]:
        """Nothing here blocks automatically — a human reviews all of it anyway.

        Kept as a method because the confirmation UI needs to sort by severity,
        and because a future auto-accept path would need exactly this list.
        """
        severe = {
            StructureWarningCode.QUOTE_NOT_FOUND,
            StructureWarningCode.TRUNCATED,
            StructureWarningCode.NO_EMPLOYMENT,
        }
        return [w for w in self.warnings if w.code in severe]


__all__ = [
    "CandidateName",
    "CandidateContact",
    "CandidateAchievement",
    "CandidateEmployment",
    "CandidateEducation",
    "CandidateProject",
    "CandidateCredential",
    "ExtractedDocument",
    "StructureWarningCode",
    "StructureWarning",
    "StructureResult",
    "DateRange",
    "Provenance",
]
