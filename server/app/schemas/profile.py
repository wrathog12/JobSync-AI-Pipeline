"""L1 — PROFILE. Mutable current state, exactly one value per key.

Every field here answers a DETERMINISTIC form field by key lookup: no
embedding, no LLM, no ambiguity. Crucially it can return `None`, which is the
whole point — "we don't know your GPA" must be distinguishable from "your GPA
is 0" and from "we can guess your GPA."

Staleness is tracked per dotted path in `confirmations` rather than by wrapping
every scalar in a metadata object, which would make the schema unreadable for
no gain.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .common import Money, Provenance, Source


class AuthorizationStatus(str, Enum):
    CITIZEN = "citizen"
    PERMANENT_RESIDENT = "permanent_resident"
    VISA = "visa"
    NONE = "none"
    UNKNOWN = "unknown"


class RemotePreference(str, Enum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    NO_PREFERENCE = "no_preference"


class Location(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None
    postal: str | None = None

    def one_line(self) -> str:
        return ", ".join(p for p in (self.city, self.region, self.country) if p)


class Links(BaseModel):
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None
    other: dict[str, str] = Field(default_factory=dict)


class WorkAuthorization(BaseModel):
    """NEVER inferred, NEVER generated, NEVER parsed from a resume.

    A resume showing US employment does not imply US work authorization — that
    inference is wrong for a large fraction of visa holders and it is exactly
    the kind of confident, well-grounded-looking error that survives testing.
    User-entered only, and mode-immune in all modes.
    """

    country: str | None = None
    status: AuthorizationStatus = AuthorizationStatus.UNKNOWN
    requires_sponsorship: bool | None = None
    work_permit_expiry: str | None = None

    source: Source = Field(
        default=Source.USER_ENTERED,
        description="Pinned to USER_ENTERED. A parser must not write this.",
    )
    confirmed_at: datetime | None = None


class Preferences(BaseModel):
    desired_comp: Money | None = None
    notice_period_days: int | None = None
    earliest_start: str | None = None
    remote_preference: RemotePreference = RemotePreference.NO_PREFERENCE
    willing_to_relocate: bool | None = None


#: Paths we nag the user to re-confirm, and after how long.
STALE_AFTER_DAYS: dict[str, int] = {
    "location": 180,
    "phone_e164": 365,
    "authorization": 180,
    "preferences.desired_comp": 180,
}


class Profile(BaseModel):
    email: str | None = None
    phone_e164: str | None = Field(default=None, description="E.164, e.g. +14155550123")
    location: Location = Field(default_factory=Location)
    links: Links = Field(default_factory=Links)
    authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    preferences: Preferences = Field(default_factory=Preferences)

    confirmations: dict[str, datetime] = Field(
        default_factory=dict,
        description="Dotted path -> last human confirmation. Drives staleness prompts.",
    )
    provenance: Provenance

    def stale_paths(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        out: list[str] = []
        for path, max_days in STALE_AFTER_DAYS.items():
            seen = self.confirmations.get(path)
            if seen is None or (now - seen).days > max_days:
                out.append(path)
        return out


__all__ = [
    "AuthorizationStatus",
    "RemotePreference",
    "Location",
    "Links",
    "WorkAuthorization",
    "Preferences",
    "Profile",
]
