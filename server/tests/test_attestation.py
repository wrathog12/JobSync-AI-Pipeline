"""The deny-list tests. Phase 0 exit criterion: these must be green.

The assertion that matters most is `test_zero_attestation_fields_ever_answered`:
no attestation field may ever come back with a value, in any mode.
"""

from __future__ import annotations

import pytest

from app.memory.store import get_demo_store
from app.pipeline.answer import run
from app.pipeline.classify import classify
from app.schemas.common import GenerationMode
from app.schemas.field import Constraints, FieldClass, FieldType, FormField
from app.schemas.trace import AnswerRequest
from app.taxonomy import attestation

ATTESTATION_LABELS = [
    "Do you require sponsorship to work in the United States?",
    "Are you legally authorized to work in the US?",
    "Are you authorised to work in the UK?",
    "What is your visa status?",
    "Do you now or will you in the future require a work permit?",
    "Do you have the right to work in Canada?",
    "Have you ever been convicted of a felony?",
    "Do you consent to a background check?",
    "Will you consent to a drug test?",
    "What is your GPA?",
    "Cumulative grade point average",
    "Do you hold an active security clearance?",
    "Please list your professional licenses",
    "Race / Ethnicity (voluntary)",
    "Gender (voluntary self-identification)",
    "Are you a protected veteran?",
    "Do you have a disability?",
    "What is your current salary?",
    "Please provide your salary history",
    "I certify that the above information is true and complete",
    "I attest that all statements are accurate",
    "Electronic signature",
]

SAFE_LABELS = [
    "First name",
    "Email address",
    "LinkedIn profile",
    "Why do you want this role?",
    "Describe a technical challenge you solved",
    "Tell us about a time you led a team",
    "Notice period",
    "City",
]


@pytest.mark.parametrize("label", ATTESTATION_LABELS)
def test_denylist_catches_attestation_labels(label: str) -> None:
    assert attestation.is_attestation(label), f"deny-list missed: {label!r}"
    assert attestation.explain(label)


@pytest.mark.parametrize("label", SAFE_LABELS)
def test_denylist_does_not_overreach(label: str) -> None:
    assert not attestation.is_attestation(label), f"false positive on: {label!r}"


@pytest.mark.parametrize("label", ATTESTATION_LABELS)
def test_classifier_routes_to_attestation(label: str) -> None:
    field = classify(FormField(id="f1", type=FieldType.TEXTAREA, context_label=label))
    assert field.field_class is FieldClass.ATTESTATION


@pytest.mark.parametrize("label", ATTESTATION_LABELS)
@pytest.mark.parametrize("mode", list(GenerationMode))
def test_zero_attestation_fields_ever_answered(label: str, mode: GenerationMode) -> None:
    """The non-negotiable invariant. No mode, ever, may fill one of these."""
    trace = run(AnswerRequest(question=label, mode=mode, max_chars=500), get_demo_store())
    assert trace.field.field_class is FieldClass.ATTESTATION
    assert trace.abstained is True
    assert trace.answer is None, f"{mode.value} filled an attestation field: {label!r}"
    assert trace.needs_review is True, "an attestation field must reach the human"


def test_fail_closed_on_unclassifiable_short_field() -> None:
    """An unidentifiable short input is ATTESTATION, never GENERATIVE."""
    field = classify(
        FormField(
            id="f1",
            type=FieldType.TEXT,
            context_label="Reference contact for verification purposes",
            constraints=Constraints(max_value=40),
        )
    )
    assert field.field_class is FieldClass.ATTESTATION
    assert field.classified_via == "fail_closed"


def test_denylist_version_is_pinned() -> None:
    """Bump deliberately — this test exists to make a silent change impossible."""
    assert attestation.VERSION == 1
