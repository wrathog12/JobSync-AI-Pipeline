"""Alias resolution and the three-way routing."""

from __future__ import annotations

import pytest

from app.pipeline.classify import classify
from app.schemas.field import Constraints, FieldClass, FieldType, FormField
from app.taxonomy import canonical_questions as cq


@pytest.mark.parametrize(
    "label,expected_id",
    [
        ("Email", "email"),
        ("Email address", "email"),
        ("What is your email address?", "email"),
        ("First name", "first_name"),
        ("Legal first name", "first_name"),
        ("Phone number", "phone"),
        ("LinkedIn URL", "linkedin"),
        ("Current title", "current_title"),
        ("What is your current title?", "current_title"),
        ("Years of experience", "years_experience"),
        ("Why do you want this role?", "why_this_role"),
        ("Tell us about a time something went wrong and what you learned.", "failure_example"),
        ("Describe a technical challenge you solved", "technical_challenge"),
        (
            "Tell us about a time you had to influence stakeholders without direct authority.",
            "influence_example",
        ),
    ],
)
def test_alias_resolution(label: str, expected_id: str) -> None:
    resolved, confidence = cq.resolve(label)
    assert resolved is not None, f"no match for {label!r}"
    assert resolved.id == expected_id
    assert confidence >= 0.55


def test_unigram_alias_does_not_hijack_a_long_label() -> None:
    """'name' must not resolve someone else's name to the user's own.

    This was a live bug: the field asks for a manager, and a naive unigram
    match filled the candidate's legal name into it.
    """
    resolved, _ = cq.resolve("What is the name of your current manager?")
    assert resolved is None or resolved.id != "full_name"


def test_deterministic_fields_carry_a_profile_path() -> None:
    field = classify(FormField(id="f1", type=FieldType.TEXT, context_label="Email address"))
    assert field.field_class is FieldClass.DETERMINISTIC
    assert field.profile_path == "profile.email"


def test_generative_fields_carry_competency_tags() -> None:
    field = classify(
        FormField(
            id="f1",
            type=FieldType.TEXTAREA,
            context_label="Tell us about a time you had to influence stakeholders "
            "without direct authority.",
        )
    )
    assert field.field_class is FieldClass.GENERATIVE
    assert "influence_without_authority" in field.competency_tags


def test_long_textarea_falls_through_to_generative() -> None:
    field = classify(
        FormField(
            id="f1",
            type=FieldType.TEXTAREA,
            context_label="Anything else you would like the hiring team to know?",
            constraints=Constraints(max_value=2000),
        )
    )
    assert field.field_class is FieldClass.GENERATIVE
