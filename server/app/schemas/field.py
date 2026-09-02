"""Form fields, their constraints, and the three-way classification.

The classification is enforced server-side before inference, and it fails
closed: anything unclassifiable becomes ATTESTATION, never GENERATIVE.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FieldClass(str, Enum):
    DETERMINISTIC = "deterministic"
    GENERATIVE = "generative"
    ATTESTATION = "attestation"


class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    DATE = "date"
    NUMBER = "number"
    UNKNOWN = "unknown"


class LimitUnit(str, Enum):
    CHARS = "chars"
    WORDS = "words"
    SENTENCES = "sentences"


class Constraints(BaseModel):
    """Extracted client-side, because a limit is a property of the page.

    The unit is captured, not discarded: 500 words and 500 chars differ ~6x, and
    a 500-word answer squeezed into 500 chars is unusable.
    """

    max_value: int | None = None
    min_value: int | None = None
    unit: LimitUnit = LimitUnit.CHARS
    is_required: bool = False
    extracted_from: str | None = Field(
        default=None, description="'maxLength' | 'placeholder' | 'helper_text' | 'counter'"
    )

    @property
    def max_chars(self) -> int | None:
        """Normalize to characters for the length budget."""
        if self.max_value is None:
            return None
        if self.unit == LimitUnit.CHARS:
            return self.max_value
        if self.unit == LimitUnit.WORDS:
            return self.max_value * 6
        return self.max_value * 120


class FormField(BaseModel):
    """What the extension sends. The backend never needs to understand the DOM."""

    id: str
    type: FieldType = FieldType.UNKNOWN
    context_label: str
    constraints: Constraints = Field(default_factory=Constraints)
    options: list[str] = Field(default_factory=list, description="For select / radio.")


class ClassifiedField(FormField):
    field_class: FieldClass
    canonical_question_id: str | None = None
    competency_tags: list[str] = Field(default_factory=list)
    classified_via: str = Field(
        default="unknown",
        description="'attestation_denylist' | 'alias_dict' | 'adapter_map' | 'llm' | 'fail_closed'",
    )
    classifier_confidence: float = 0.0
    profile_path: str | None = Field(
        default=None, description="For DETERMINISTIC: the L0/L1/L2 key to read."
    )


__all__ = [
    "FieldClass",
    "FieldType",
    "LimitUnit",
    "Constraints",
    "FormField",
    "ClassifiedField",
]
