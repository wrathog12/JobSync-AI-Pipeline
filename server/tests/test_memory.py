"""Memory layers: derivation, provenance, and the abstention gate."""

from __future__ import annotations

from app.memory.store import MemoryStore, get_store
from app.pipeline.answer import run
from app.schemas.common import GenerationMode
from app.schemas.trace import AnswerRequest, Stage, StageStatus


def test_fixture_loads_all_layers() -> None:
    store = get_store()
    assert store.identity is not None and store.identity.locked
    assert store.profile is not None
    assert len(store.ledger.active_employment()) == 2
    assert store.evidence.chunks
    assert store.graph.skills


def test_derived_layers_are_rebuildable() -> None:
    """L3/L4 must be droppable and reconstructible from L2 alone."""
    store = MemoryStore()
    store.load_fixture()
    before = [c.chunk_id for c in store.evidence.chunks]

    store.evidence.chunks = []
    store.graph.skills = []
    store.rebuild_derived()

    assert [c.chunk_id for c in store.evidence.chunks] == before


def test_every_chunk_carries_provenance_home() -> None:
    """No chunk may exist without a hard FK to its L2 parent."""
    store = get_store()
    for chunk in store.evidence.chunks:
        assert chunk.entity_id, f"{chunk.chunk_id} has no entity_id"
        assert chunk.content_hash


def test_attributed_text_names_the_employer() -> None:
    """Cross-attribution must be structurally unavailable, not just discouraged."""
    store = get_store()
    chunk = next(c for c in store.evidence.chunks if c.employer_name)
    assert chunk.employer_name in chunk.attributed_text()
    assert chunk.dates.label() in chunk.attributed_text()


def test_personal_project_does_not_borrow_an_employer_name() -> None:
    store = get_store()
    chunk = store.evidence.by_id("ch_prj_01")
    assert chunk is not None
    assert chunk.employer_name is None
    assert "Personal" in chunk.attributed_text()


def test_unbacked_skill_is_surfaced_not_asserted() -> None:
    """GraphQL is declared in the fixture with no supporting achievement."""
    store = get_store()
    unbacked = {s.name for s in store.graph.unbacked_skills()}
    assert "GraphQL" in unbacked

    backed = store.graph.skill_by_name("PostgreSQL")
    assert backed is not None and backed.is_backed


def test_soft_skill_gaps_are_visible() -> None:
    """A competency with zero evidence is not answerable, and we know which."""
    store = get_store()
    gaps = {c.tag for c in store.graph.gaps()}
    assert gaps, "fixture should have at least one uncovered competency"
    for tag in gaps:
        node = store.graph.competency(tag)
        assert node is not None and not node.is_answerable


def test_years_experience_is_computed_not_generated() -> None:
    store = get_store()
    assert store.ledger.total_years_experience() > 4.0


def test_null_gpa_stays_null() -> None:
    """'We don't know your GPA' must not collapse into 'your GPA is 0'."""
    store = get_store()
    edu = store.ledger.education[0]
    assert edu.gpa is None


def test_deterministic_lookup_can_return_not_set() -> None:
    store = get_store()
    assert store.resolve_path("profile.email") == "adi.raman@example.com"
    assert store.resolve_path("profile.links.portfolio") is None


def test_abstains_on_unanswerable_question() -> None:
    """The single most important safety mechanism: no evidence, no answer."""
    trace = run(
        AnswerRequest(question="Describe your experience managing a P&L.", max_chars=500),
        get_store(),
    )
    assert trace.abstained is True
    assert trace.answer is None
    gate = trace.step(Stage.SUFFICIENCY_GATE)
    assert gate is not None and gate.status is StageStatus.ABSTAINED


def test_answer_memory_hit_costs_zero_tokens() -> None:
    trace = run(
        AnswerRequest(
            question="Tell us about a time something went wrong and what you learned.",
            max_chars=800,
        ),
        get_store(),
    )
    step = trace.step(Stage.ANSWER_MEMORY)
    assert step is not None and step.status is StageStatus.HIT
    assert trace.total_tokens == 0
    assert trace.answer


def test_retrieval_picks_the_right_chunk_for_a_behavioural_question() -> None:
    """Regression: BM25 alone returned the worst available chunk here, because
    the only word shared with the question was 'time'."""
    trace = run(
        AnswerRequest(
            question="Tell us about a time you had to influence stakeholders "
            "without direct authority.",
            max_chars=500,
        ),
        get_store(),
    )
    rerank = trace.step(Stage.RERANK)
    assert rerank is not None
    assert rerank.chunks[0].chunk_id == "ch_ach_01_03"


def test_grounding_check_passes_on_strict_output() -> None:
    trace = run(
        AnswerRequest(question="Describe a technical challenge you solved.", max_chars=600),
        get_store(),
    )
    step = trace.step(Stage.GROUND_CHECK)
    assert step is not None
    assert step.violations == [], [v.token for v in step.violations]


def test_strict_mode_never_stretches() -> None:
    trace = run(
        AnswerRequest(
            question="Describe a technical challenge you solved.",
            mode=GenerationMode.STRICT,
            jd_text="We need deep Kubernetes and Terraform expertise, 5+ years.",
            max_chars=600,
        ),
        get_store(),
    )
    assert trace.claim_distance == 0.0
    assert trace.stretches == []


def test_aggressive_mode_records_what_it_stretched() -> None:
    """Embellishment is only usable if it is auditable."""
    trace = run(
        AnswerRequest(
            question="Describe a technical challenge you solved.",
            mode=GenerationMode.AGGRESSIVE,
            jd_text="We need deep Kubernetes and Terraform expertise, 5+ years.",
            max_chars=600,
        ),
        get_store(),
    )
    assert trace.max_claim_distance == 0.70
    for stretch in trace.stretches:
        assert stretch.distance <= trace.max_claim_distance
        assert stretch.note


def test_length_limit_is_respected() -> None:
    trace = run(
        AnswerRequest(question="Describe a technical challenge you solved.", max_chars=180),
        get_store(),
    )
    if trace.answer:
        assert len(trace.answer) <= 180
