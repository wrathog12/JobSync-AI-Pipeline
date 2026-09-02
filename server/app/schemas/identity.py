"""L0 — IDENTITY. Write-once, then locked.

Not "immutable": legal names change on marriage, citizenship changes on
naturalization. The correct model is *locked after confirmation*, with an
explicit re-confirm flow to change anything. Modeling it as truly immutable
buys a migration in year one.

L0 is never embedded, never chunked, and never placed in a generation prompt.
It is read by key lookup only, and every field in it is mode-immune.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .common import Provenance


class Identity(BaseModel):
    legal_first: str
    legal_middle: str | None = None
    legal_last: str
    preferred_name: str | None = Field(
        default=None,
        description="What forms should show when they ask for a display name.",
    )

    date_of_birth: str | None = Field(
        default=None, description="YYYY-MM-DD. Highest-sensitivity field in the system."
    )
    citizenship: list[str] = Field(
        default_factory=list, description="ISO 3166-1 alpha-2 codes. Feeds ATTESTATION gating."
    )
    pronouns: str | None = Field(
        default=None,
        description="Self-identified only. Never inferred from a name.",
    )

    locked: bool = Field(
        default=False,
        description="True once the user has confirmed. Writes then require an unlock.",
    )
    locked_at: datetime | None = None
    provenance: Provenance

    def full_legal_name(self) -> str:
        parts = [self.legal_first, self.legal_middle, self.legal_last]
        return " ".join(p for p in parts if p)

    def display_name(self) -> str:
        return self.preferred_name or self.legal_first


__all__ = ["Identity"]
