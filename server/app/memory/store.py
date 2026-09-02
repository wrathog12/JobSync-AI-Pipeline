"""The memory store. Phase 0: in-process, single user, loaded from a fixture.

Phase 1 swaps the body of this class for Postgres. Everything upstream talks to
`MemoryStore` and never to a database, so that swap touches one file.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas.answer_memory import AnswerMemory, ApprovedAnswer
from ..schemas.competency import CompetencyGraph, SkillNode
from ..schemas.evidence import EvidenceIndex
from ..schemas.identity import Identity
from ..schemas.ledger import Ledger
from ..schemas.profile import Profile
from .derive import build_competency_graph, build_evidence_index

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "profiles"
DEFAULT_FIXTURE = FIXTURE_DIR / "sample_profile.json"


class MemoryStore:
    """All six layers, with the derived two rebuilt on every commit."""

    def __init__(self) -> None:
        self.identity: Identity | None = None
        self.profile: Profile | None = None
        self.ledger: Ledger = Ledger()
        self.declared_skills: list[SkillNode] = []
        self.evidence: EvidenceIndex = EvidenceIndex()
        self.graph: CompetencyGraph = CompetencyGraph()
        self.answers: AnswerMemory = AnswerMemory()

    # ── loading ────────────────────────────────────────────────────────────────

    def load_fixture(self, path: Path | None = None) -> None:
        path = path or DEFAULT_FIXTURE
        raw = json.loads(path.read_text(encoding="utf-8"))

        self.identity = Identity.model_validate(raw["identity"])
        self.profile = Profile.model_validate(raw["profile"])
        self.ledger = Ledger.model_validate(raw["ledger"])
        self.declared_skills = [SkillNode.model_validate(s) for s in raw.get("declared_skills", [])]
        self.answers = AnswerMemory(
            answers=[ApprovedAnswer.model_validate(a) for a in raw.get("answer_memory", [])]
        )
        self.rebuild_derived()

    def rebuild_derived(self) -> None:
        """L3 and L4 are disposable. This is the only way they are ever written."""
        self.evidence = build_evidence_index(self.ledger)
        self.graph = build_competency_graph(self.ledger, self.evidence, self.declared_skills)

    # ── L0/L1/L2 key lookup: the DETERMINISTIC path, zero tokens ──────────────

    def resolve_path(self, path: str) -> object | None:
        """Read a dotted profile path. Returns None for 'not set', which is a
        real answer — the caller must prompt the user rather than guess."""
        if path == "identity.full_legal_name":
            return self.identity.full_legal_name() if self.identity else None
        if path == "ledger.total_years_experience":
            return self.ledger.total_years_experience()

        if path.startswith("ledger.employment.current."):
            attr = path.rsplit(".", 1)[-1]
            current = next((e for e in self.ledger.active_employment() if e.dates.is_current), None)
            return getattr(current, attr, None) if current else None

        if path.startswith("ledger.education.latest."):
            attr = path.rsplit(".", 1)[-1]
            grads = [e for e in self.ledger.education if e.is_active]
            latest = max(grads, key=lambda e: e.dates.end or "", default=None)
            if latest is None:
                return None
            return getattr(latest, "field_of_study" if attr == "field" else attr, None)

        root, *rest = path.split(".")
        node: object | None = {"identity": self.identity, "profile": self.profile}.get(root)
        for part in rest:
            if node is None:
                return None
            node = getattr(node, part, None)
        return node

    # ── stats for the viewer ──────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "identity_locked": bool(self.identity and self.identity.locked),
            "employment_records": len(self.ledger.active_employment()),
            "education_records": len([e for e in self.ledger.education if e.is_active]),
            "project_records": len([p for p in self.ledger.projects if p.is_active]),
            "credential_records": len(self.ledger.credentials),
            "evidence_chunks": len(self.evidence.chunks),
            "skills": len(self.graph.skills),
            "unbacked_skills": [s.name for s in self.graph.unbacked_skills()],
            "answerable_competencies": len([c for c in self.graph.competencies if c.is_answerable]),
            "competency_gaps": [c.tag for c in self.graph.gaps()],
            "thin_competencies": [c.tag for c in self.graph.competencies if c.is_thin],
            "approved_answers": len(self.answers.answers),
            "total_years_experience": self.ledger.total_years_experience(),
            "stale_paths": self.profile.stale_paths() if self.profile else [],
        }


#: Phase 0 single-process singleton. Phase 1 makes this per-user and DB-backed.
STORE = MemoryStore()


def get_store() -> MemoryStore:
    if STORE.identity is None:
        STORE.load_fixture()
    return STORE


__all__ = ["MemoryStore", "STORE", "get_store", "DEFAULT_FIXTURE"]
