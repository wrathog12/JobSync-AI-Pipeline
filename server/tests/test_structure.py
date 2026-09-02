"""Structuring tests.

Almost all of these exercise `build_result`, which is pure: model output plus
source text in, candidate records and warnings out. That is deliberate — the
verification rules are where the value is, and pinning them to a scripted client
would test the script instead of the rule.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMResponse, LLMUsage
from app.llm.fake import FakeClient
from app.pipeline.structure import (
    SYSTEM,
    build_result,
    structure_document,
)
from app.schemas.common import Confidence, Source
from app.schemas.ingest import DocumentKind, Layout, RawDocument, sha256_bytes
from app.schemas.ledger import EmploymentType
from app.schemas.structured import (
    CandidateAchievement,
    CandidateContact,
    CandidateEducation,
    CandidateEmployment,
    CandidateName,
    CandidateProject,
    ExtractedDocument,
    StructureWarningCode,
)

RESUME = """\
Priya Raghunathan
Senior Backend Engineer
priya.r@example.com | +1 415 555 0134 | San Francisco, CA
linkedin.com/in/praghunathan | github.com/praghu

EXPERIENCE

Northwind Logistics — Staff Engineer
Mar 2021 - Present, San Francisco, CA
- Cut median checkout latency from 840ms to 310ms by replacing a synchronous
  pricing call with a cached read path.
- Led the migration of 47 services off a shared Postgres instance, eliminating
  the weekly lock contention incidents.

Cobalt Systems — Senior Software Engineer
June 2018 - February 2021
- Built the billing reconciliation pipeline that recovered $1.2M in unbilled usage
  in its first quarter.

EDUCATION

B.S. Computer Science, University of Illinois Urbana-Champaign, 2018
GPA 3.7

PROJECTS

pgshard — open-source Postgres sharding proxy. 1.4K stars.

SKILLS
Python, Go, PostgreSQL, Kafka, Kubernetes
"""


def raw_doc(text: str = RESUME, doc_id: str = "doc_abcdef1234567890") -> RawDocument:
    return RawDocument(
        doc_id=doc_id,
        kind=DocumentKind.PDF,
        filename="resume.pdf",
        text=text,
        page_count=1,
        layout=Layout.SINGLE_COLUMN,
        warnings=[],
        sha256=sha256_bytes(text.encode()),
    )


def extracted(**overrides) -> ExtractedDocument:
    """A faithful extraction of RESUME, so tests can perturb one thing at a time."""
    base = dict(
        name=CandidateName(legal_first="Priya", legal_last="Raghunathan"),
        contact=CandidateContact(
            email="priya.r@example.com",
            phone="+1 415 555 0134",
            city="San Francisco",
            region="CA",
            linkedin="linkedin.com/in/praghunathan",
            github="github.com/praghu",
        ),
        headline="Senior Backend Engineer",
        employment=[
            CandidateEmployment(
                employer="Northwind Logistics",
                title="Staff Engineer",
                start="2021-03",
                end=None,
                is_current=True,
                location="San Francisco, CA",
                achievements=[
                    CandidateAchievement(
                        text=(
                            "Cut median checkout latency from 840ms to 310ms by replacing a "
                            "synchronous pricing call with a cached read path."
                        )
                    ),
                    CandidateAchievement(
                        text=(
                            "Led the migration of 47 services off a shared Postgres instance, "
                            "eliminating the weekly lock contention incidents."
                        )
                    ),
                ],
            ),
            CandidateEmployment(
                employer="Cobalt Systems",
                title="Senior Software Engineer",
                start="2018-06",
                end="2021-02",
                is_current=False,
                achievements=[
                    CandidateAchievement(
                        text=(
                            "Built the billing reconciliation pipeline that recovered $1.2M in "
                            "unbilled usage in its first quarter."
                        )
                    )
                ],
            ),
        ],
        education=[
            CandidateEducation(
                institution="University of Illinois Urbana-Champaign",
                degree="B.S.",
                field_of_study="Computer Science",
                end="2018",
                gpa=3.7,
            )
        ],
        projects=[
            CandidateProject(
                name="pgshard",
                summary="open-source Postgres sharding proxy",
                employer=None,
            )
        ],
        skills=["Python", "Go", "PostgreSQL", "Kafka", "Kubernetes"],
    )
    base.update(overrides)
    return ExtractedDocument(**base)


# ── the schema the model must not be able to write to ──────────────────────────


def test_the_extraction_schema_has_no_work_authorization_field():
    """Structural, not behavioural. `WorkAuthorization` is pinned to USER_ENTERED
    because a résumé showing US employment does not imply US work authorization —
    an inference that is wrong for a large share of visa holders and looks
    perfectly well-grounded when it is. Leaving the field out of the schema means
    no prompt edit can start filling it in.
    """
    fields = _all_field_names(ExtractedDocument)
    for banned in ("citizenship", "visa", "sponsorship", "authorization", "work_permit"):
        offenders = [f for f in fields if banned in f and f != "mentions_work_authorization"]
        assert not offenders, f"extraction schema exposes {offenders}"


def test_the_extraction_schema_cannot_set_its_own_confidence():
    """Same reasoning as the classifier invariant: if the model could emit
    `VERIFIED`, unconfirmed parse output would reach the DETERMINISTIC fill path."""
    fields = _all_field_names(ExtractedDocument)
    for banned in ("confidence", "provenance", "confirmed_at", "verified", "locked"):
        assert banned not in fields


def test_the_extraction_schema_does_not_let_the_model_mint_ids():
    """Ids are minted from the document so re-parsing is idempotent. A model-chosen
    id would collide or drift between runs."""
    assert "id" not in _all_field_names(ExtractedDocument)


def test_the_extraction_schema_is_accepted_by_the_gemini_sdk():
    """Nested models and optionals in a `response_schema` are exactly where the
    SDK's converter gives up, and finding that out on the first real call wastes a
    document upload."""
    gt = pytest.importorskip("google.genai.types")
    config = gt.GenerateContentConfig(
        response_mime_type="application/json", response_schema=ExtractedDocument
    )
    assert config.response_schema is ExtractedDocument


def _all_field_names(model, seen=None) -> set[str]:
    from pydantic import BaseModel

    seen = seen if seen is not None else set()
    out: set[str] = set()
    if model in seen:
        return out
    seen.add(model)
    for name, field in model.model_fields.items():
        out.add(name)
        for arg in (field.annotation, *getattr(field.annotation, "__args__", ())):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                out |= _all_field_names(arg, seen)
    return out


# ── provenance is stamped by us ────────────────────────────────────────────────


def test_everything_lands_unconfirmed():
    res = build_result(extracted(), raw_doc())
    records = [
        res.identity,
        res.profile,
        *res.ledger.employment,
        *res.ledger.education,
        *res.ledger.projects,
    ]
    for rec in records:
        assert rec is not None
        assert rec.provenance.confidence is Confidence.PARSED_UNCONFIRMED
        assert rec.provenance.source is Source.PARSED_RESUME
        assert rec.provenance.confirmed_at is None
        assert rec.provenance.is_confirmed is False


def test_identity_is_not_locked_by_parsing():
    """L0 locks on human confirmation. Locking here would make a parse error
    permanent and need an unlock flow to fix."""
    res = build_result(extracted(), raw_doc())
    assert res.identity is not None
    assert res.identity.locked is False
    assert res.identity.locked_at is None


def test_work_authorization_stays_unknown_after_parsing():
    from app.schemas.profile import AuthorizationStatus

    res = build_result(extracted(), raw_doc())
    assert res.profile is not None
    assert res.profile.authorization.status is AuthorizationStatus.UNKNOWN
    assert res.profile.authorization.source is Source.USER_ENTERED
    assert res.profile.authorization.requires_sponsorship is None


def test_a_mention_of_sponsorship_asks_the_user_instead_of_reading_it():
    """The honest version of helpful: we noticed, we deliberately did not read it,
    here is what to do."""
    res = build_result(extracted(mentions_work_authorization=True), raw_doc())
    warn = next(
        w for w in res.warnings if w.code is StructureWarningCode.AUTHORIZATION_MENTIONED
    )
    assert "yourself" in warn.message
    assert res.profile.authorization.requires_sponsorship is None


def test_nothing_is_confirmed_and_nothing_is_stored():
    """Structuring must not touch durable memory; step 4 is the only writer."""
    from app.memory.store import get_demo_store

    store = get_demo_store()
    before = store.stats()
    build_result(extracted(), raw_doc())
    assert store.stats() == before


# ── quote verification: the check that keeps evidence real ─────────────────────


def test_verbatim_bullets_are_accepted():
    res = build_result(extracted(), raw_doc())
    assert res.achievement_count == 3
    assert res.unverified_quotes == 0


def test_a_bullet_that_survives_line_wrapping_is_still_verbatim():
    """The source wraps mid-sentence, so the copied bullet has a newline where the
    document had one. Normalizing whitespace is the point of the check's
    normalization step, not a loophole in it."""
    res = build_result(extracted(), raw_doc())
    wrapped = res.ledger.employment[0].achievements[0]
    assert "\n" in RESUME[RESUME.index("Cut median") : RESUME.index("Led the")]
    assert wrapped.text.startswith("Cut median checkout latency")
    assert res.unverified_quotes == 0


def test_a_paraphrased_bullet_is_flagged():
    """The failure this whole check exists for. A rewritten bullet becomes an L3
    chunk that the grounding check then treats as ground truth, so future claims
    get validated against model prose."""
    doc = extracted()
    doc.employment[0].achievements[0] = CandidateAchievement(
        text="Improved checkout performance substantially through caching improvements."
    )
    res = build_result(doc, raw_doc())
    assert res.unverified_quotes == 1
    warn = next(w for w in res.warnings if w.code == StructureWarningCode.QUOTE_NOT_FOUND)
    assert "Northwind" in warn.message
    assert warn.record_id is not None


def test_an_invented_bullet_is_flagged():
    doc = extracted()
    doc.employment[1].achievements.append(
        CandidateAchievement(text="Mentored a team of eight junior engineers.")
    )
    res = build_result(doc, raw_doc())
    assert res.unverified_quotes == 1


def test_a_dropped_full_stop_does_not_fail_the_check():
    """0.90 rather than 1.00 on purpose: a check that fires on punctuation is noise
    and gets ignored, which costs more than it saves."""
    doc = extracted()
    original = doc.employment[1].achievements[0].text
    doc.employment[1].achievements[0] = CandidateAchievement(text=original.rstrip("."))
    res = build_result(doc, raw_doc())
    assert res.unverified_quotes == 0


def test_a_flagged_bullet_is_still_kept_for_review():
    """Dropping it would leave the user comparing our list against their résumé to
    find what went missing. Keeping it flagged puts the decision in front of them."""
    doc = extracted()
    doc.employment[0].achievements[0] = CandidateAchievement(text="Made things faster.")
    res = build_result(doc, raw_doc())
    assert len(res.ledger.employment[0].achievements) == 2
    assert res.blocking()


def test_blank_bullets_are_dropped_not_flagged():
    doc = extracted()
    doc.employment[0].achievements.append(CandidateAchievement(text="   "))
    res = build_result(doc, raw_doc())
    assert res.achievement_count == 3
    assert res.unverified_quotes == 0


# ── dates ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2019-03", "2019-03"),
        ("2019-3", "2019-03"),
        ("03/2019", "2019-03"),
        ("2019/03", "2019-03"),
        ("Mar 2019", "2019-03"),
        ("March 2019", "2019-03"),
        ("Sept 2019", "2019-09"),
        ("2019 December", "2019-12"),
    ],
)
def test_date_formats_normalize_to_year_month(raw, expected):
    doc = extracted()
    doc.employment[1].start = raw
    res = build_result(doc, raw_doc())
    assert res.ledger.employment[1].dates.start == expected


def test_a_bare_year_is_snapped_and_the_approximation_is_disclosed():
    doc = extracted()
    doc.employment[1].start = "2018"
    res = build_result(doc, raw_doc())
    assert res.ledger.employment[1].dates.start == "2018-01"
    assert any(w.code == StructureWarningCode.DATE_IMPRECISE for w in res.warnings)


def test_a_bare_end_year_snaps_to_december():
    """Snapping an end date to January would erase eleven months of a real job."""
    res = build_result(extracted(), raw_doc())
    assert res.ledger.education[0].dates.end == "2018-12"


def test_is_current_is_what_makes_a_role_current_not_a_missing_end_date():
    res = build_result(extracted(), raw_doc())
    assert res.ledger.employment[0].dates.is_current is True
    assert res.ledger.employment[1].dates.is_current is False


def test_an_unreadable_end_date_does_not_silently_become_an_ongoing_job():
    """The expensive failure. `DateRange` reads end=None as current and
    `total_years_experience` counts a current role to today, so a 2015 internship
    with a mangled end date would quietly add a decade of experience.
    """
    doc = extracted()
    doc.employment[1].end = "sometime in early '21"
    doc.employment[1].is_current = False
    res = build_result(doc, raw_doc())

    job = res.ledger.employment[1]
    assert job.dates.end is None, "unparseable, so it stays empty"
    warn = next(w for w in res.warnings if w.code == StructureWarningCode.DATE_UNPARSEABLE)
    assert "inflate" in warn.message
    assert warn.record_id == job.id


def test_present_in_the_end_field_is_treated_as_current():
    doc = extracted()
    doc.employment[1].end = "Present"
    res = build_result(doc, raw_doc())
    assert res.ledger.employment[1].dates.end is None
    assert not any(w.code == StructureWarningCode.DATE_UNPARSEABLE for w in res.warnings)


def test_reversed_dates_are_flagged():
    doc = extracted()
    doc.employment[1].start = "2021-06"
    doc.employment[1].end = "2018-02"
    res = build_result(doc, raw_doc())
    assert any(w.code == StructureWarningCode.DATE_REVERSED for w in res.warnings)


def test_two_current_roles_are_flagged_without_being_rejected():
    """Legitimately happens — a day job and a contract. Worth a nudge, not a veto."""
    doc = extracted()
    doc.employment[1].is_current = True
    res = build_result(doc, raw_doc())
    warn = next(w for w in res.warnings if w.code == StructureWarningCode.MULTIPLE_CURRENT)
    assert "Cobalt Systems" in warn.message
    assert res.ledger.employment[1].dates.is_current is True


# ── project attribution ────────────────────────────────────────────────────────


def test_a_project_is_linked_to_a_listed_employer():
    doc = extracted()
    doc.projects[0].employer = "Northwind Logistics"
    res = build_result(doc, raw_doc())
    assert res.ledger.projects[0].employer_id == res.ledger.employment[0].id


def test_employer_matching_ignores_case_and_padding():
    doc = extracted()
    doc.projects[0].employer = "  northwind logistics "
    res = build_result(doc, raw_doc())
    assert res.ledger.projects[0].employer_id == res.ledger.employment[0].id


def test_an_unknown_employer_demotes_the_project_instead_of_guessing():
    """No fuzzy matching here on purpose: attaching a project to the wrong employer
    manufactures a claim the applicant has to defend in an interview."""
    doc = extracted()
    doc.projects[0].employer = "Acme Corp"
    res = build_result(doc, raw_doc())
    assert res.ledger.projects[0].employer_id is None
    warn = next(
        w for w in res.warnings if w.code == StructureWarningCode.UNKNOWN_PROJECT_EMPLOYER
    )
    assert "pgshard" in warn.message and "Acme Corp" in warn.message


def test_a_personal_project_stays_personal():
    res = build_result(extracted(), raw_doc())
    assert res.ledger.projects[0].employer_id is None
    assert not any(
        w.code == StructureWarningCode.UNKNOWN_PROJECT_EMPLOYER for w in res.warnings
    )


# ── contact details ────────────────────────────────────────────────────────────


def test_the_phone_number_is_not_reformatted():
    """E.164 needs a country, and inferring one from a résumé's location is how a
    US number acquires a +44."""
    res = build_result(extracted(), raw_doc())
    assert res.profile.phone_e164 == "+1 415 555 0134"


def test_missing_contact_fields_stay_none_rather_than_empty_string():
    """"Not stated" has to be distinguishable from "set to blank", because the
    DETERMINISTIC path returns None to mean "ask the user"."""
    doc = extracted(contact=CandidateContact(email="  ", city=""))
    res = build_result(doc, raw_doc())
    assert res.profile.email is None
    assert res.profile.location.city is None


def test_other_urls_are_keyed_by_host():
    doc = extracted(
        contact=CandidateContact(other_urls=["https://www.stackoverflow.com/users/1", "  "])
    )
    res = build_result(doc, raw_doc())
    assert res.profile.links.other == {"stackoverflow.com": "https://www.stackoverflow.com/users/1"}


def test_a_missing_name_is_a_warning_not_a_crash():
    res = build_result(extracted(name=None), raw_doc())
    assert res.identity is None
    assert any(w.code == StructureWarningCode.NO_NAME for w in res.warnings)


def test_a_name_with_only_a_first_name_is_treated_as_missing():
    """`Identity` requires both halves, so a half-filled name would raise at
    construction — a warning the user can act on beats a 500."""
    res = build_result(
        extracted(name=CandidateName(legal_first="Priya", legal_last="  ")), raw_doc()
    )
    assert res.identity is None


# ── metrics, skills, ids ───────────────────────────────────────────────────────


def test_metrics_are_extracted_for_retrieval_weighting():
    res = build_result(extracted(), raw_doc())
    billing = res.ledger.employment[1].achievements[0]
    assert "$1.2M" in billing.metrics


def test_metrics_come_from_a_regex_not_a_model_call():
    """One call per bullet to re-derive "40%" would be the most expensive way to
    get a worse answer."""
    from app.pipeline.structure import _metrics

    assert _metrics("grew revenue 40% to $2.5M across 3x the traffic") == ["40%", "$2.5M", "3x"]
    assert _metrics("refactored the scheduler") == []


def test_declared_skills_are_kept_separate_from_the_ledger():
    """They are declared, not demonstrated. The competency graph flags any skill no
    achievement backs, and that only works if the two stay distinct."""
    res = build_result(extracted(), raw_doc())
    assert res.skills == ["Python", "Go", "PostgreSQL", "Kafka", "Kubernetes"]


def test_duplicate_skills_are_folded_case_insensitively():
    res = build_result(extracted(skills=["Python", "python", "PYTHON", "Go"]), raw_doc())
    assert res.skills == ["Python", "Go"]


def test_ids_are_deterministic_so_reparsing_does_not_duplicate():
    a = build_result(extracted(), raw_doc())
    b = build_result(extracted(), raw_doc())
    assert [e.id for e in a.ledger.employment] == [e.id for e in b.ledger.employment]
    assert [x.id for x in a.ledger.employment[0].achievements] == [
        x.id for x in b.ledger.employment[0].achievements
    ]


def test_ids_differ_across_documents():
    a = build_result(extracted(), raw_doc(doc_id="doc_1111111111111111"))
    b = build_result(extracted(), raw_doc(doc_id="doc_2222222222222222"))
    assert a.ledger.employment[0].id != b.ledger.employment[0].id


def test_employment_type_defaults_rather_than_being_inferred():
    """The model is told not to guess it from the title, so a null means the
    document did not say — and the ledger's own default applies."""
    doc = extracted()
    assert doc.employment[0].employment_type is None
    res = build_result(doc, raw_doc())
    assert res.ledger.employment[0].employment_type is EmploymentType.FULL_TIME


def test_an_empty_document_yields_a_no_employment_warning():
    res = build_result(ExtractedDocument(), raw_doc())
    codes = [w.code for w in res.warnings]
    assert StructureWarningCode.NO_EMPLOYMENT in codes
    assert StructureWarningCode.NO_NAME in codes
    assert res.record_count == 0


# ── the call itself ────────────────────────────────────────────────────────────


def test_the_document_goes_in_the_user_turn_and_the_rules_in_the_system_turn():
    """Splitting them keeps the constant part constant, which is the only caching
    available at these sizes — and stops a résumé that says "ignore the above"
    from sitting next to the rules."""
    fake = FakeClient([extracted()])
    structure_document(raw_doc(), fake)
    call = fake.last
    assert call.system == SYSTEM
    assert "Northwind Logistics" in call.prompt
    assert "Northwind Logistics" not in (call.system or "")
    assert "<document>" in call.prompt


def test_the_call_asks_for_the_schema_and_zero_temperature():
    fake = FakeClient([extracted()])
    structure_document(raw_doc(), fake)
    assert fake.last.schema is ExtractedDocument
    assert fake.last.temperature == 0.0
    assert fake.last.label == "structure"


def test_the_output_ceiling_is_raised_for_structuring():
    """A dense two-page résumé is twenty verbatim bullets plus scaffolding; the
    2048 default truncates it, and truncated JSON loses records silently."""
    from app.pipeline.structure import STRUCTURE_MAX_OUTPUT_TOKENS

    fake = FakeClient([extracted()])
    structure_document(raw_doc(), fake)
    assert fake.last.max_output_tokens == STRUCTURE_MAX_OUTPUT_TOKENS > 2048


def test_usage_and_timing_reach_the_result():
    fake = FakeClient([extracted()])
    res = structure_document(raw_doc(), fake)
    assert res.model == "fake-model"
    assert res.prompt_tokens > 0
    assert res.doc_id == "doc_abcdef1234567890"


def test_an_unusable_document_is_never_sent_to_the_model():
    """Paying for a call on a scanned PDF with no text layer produces an empty
    profile and a bill."""
    from app.schemas.ingest import ExtractionWarning, WarningCode

    doc = raw_doc(text="")
    doc.warnings.append(
        ExtractionWarning(code=WarningCode.NO_TEXT_LAYER, message="no text", blocking=True)
    )
    fake = FakeClient([extracted()])
    with pytest.raises(ValueError, match="unusable"):
        structure_document(doc, fake)
    assert fake.calls == []


def test_truncation_is_surfaced_first_because_records_are_missing():
    """It goes at the top of the list because it changes how the user should read
    everything below it: the tail of their résumé may simply be absent, and no
    per-record warning can say that."""
    doc = extracted()
    doc.employment = doc.employment[:1]  # as if the JSON ended early
    fake = FakeClient(
        [
            LLMResponse(
                text=doc.model_dump_json(),
                parsed=doc,
                usage=LLMUsage(prompt_tokens=900, output_tokens=8192),
                model="gemini-2.5-flash",
                finish_reason="MAX_TOKENS",
                truncated=True,
            )
        ]
    )
    res = structure_document(raw_doc(), fake)
    assert res.warnings[0].code is StructureWarningCode.TRUNCATED
    assert "missing" in res.warnings[0].message
    assert res.blocking()[0].code is StructureWarningCode.TRUNCATED


def test_the_prompt_forbids_the_three_things_that_matter():
    """These rules are load-bearing, not decoration: each one corresponds to a
    verification step below it or to a pinned field above it."""
    assert "character for character" in SYSTEM
    assert "NULL BEATS A GUESS" in SYSTEM
    assert "NEVER TOUCH WORK AUTHORIZATION" in SYSTEM
    assert "is_current" in SYSTEM
