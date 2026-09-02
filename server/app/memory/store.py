"""The memory store. Phase 0: in-process, single user, loaded from a fixture.

Phase 1 swaps the body of this class for Postgres. Everything upstream talks to
`MemoryStore` and never to a database, so that swap touches one file.
"""

from __future__ import annotations

import json
from pathlib import Path

from datetime import datetime, timezone

from ..schemas.answer_memory import AnswerMemory, ApprovedAnswer
from ..schemas.common import Provenance
from ..schemas.competency import CompetencyGraph, SkillNode
from ..schemas.evidence import EvidenceIndex
from ..schemas.identity import Identity
from ..schemas.ledger import Ledger
from ..schemas.profile import Profile
from .derive import build_competency_graph, build_evidence_index

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
        """Replace everything with a canned profile. Demos and tests only.

        Never call this on a store a real user has confirmed anything into. It
        overwrites L0-L2 wholesale, and because the fixture identity arrives
        `locked`, the user's own name is then refused by the L0 lock — the guard
        firing correctly in defence of a fictional person.
        """
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

    def clear(self) -> None:
        """Back to empty. The way out of a store that holds a mix of two people."""
        self.__init__()  # type: ignore[misc]

    @property
    def is_empty(self) -> bool:
        return self.identity is None and self.profile is None and not self.ledger.employment

    def rebuild_derived(self) -> None:
        """L3 and L4 are disposable. This is the only way they are ever written."""
        self.evidence = build_evidence_index(self.ledger)
        self.graph = build_competency_graph(self.ledger, self.evidence, self.declared_skills)

    # ── L0/L1/L2 key lookup: the DETERMINISTIC path, zero tokens ──────────────

    def provenance_for(self, path: str) -> Provenance | None:
        """Who vouched for the value at `path`, so callers can refuse to use it.

        `common.py` says PARSED_UNCONFIRMED must never reach a DETERMINISTIC fill
        or an ATTESTATION decision. Something has to actually check that, and it
        needs the *record's* provenance rather than the value's — L1 carries one
        provenance for the whole profile, L2 one per record.

        Returns None when there is no owning record, which callers must treat the
        same as unconfirmed rather than as permission.
        """
        if path.startswith("identity."):
            return self.identity.provenance if self.identity else None
        if path.startswith("profile."):
            return self.profile.provenance if self.profile else None

        if path == "ledger.total_years_experience":
            # Aggregate: only as trustworthy as its least-trusted input, because a
            # single unconfirmed job with a bad end date moves the total.
            active = self.ledger.active_employment()
            if not active:
                return None
            return min(
                (job.provenance for job in active),
                key=lambda p: (p.is_confirmed, p.confirmed_at or _EPOCH),
            )
        if path.startswith("ledger.employment.current."):
            current = next(
                (e for e in self.ledger.active_employment() if e.dates.is_current), None
            )
            return current.provenance if current else None
        if path.startswith("ledger.education.latest."):
            grads = [e for e in self.ledger.education if e.is_active]
            latest = max(grads, key=lambda e: e.dates.end or "", default=None)
            return latest.provenance if latest else None
        return None

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
    """The user's own memory. Starts EMPTY, and stays empty until they confirm.

    It used to lazily `load_fixture()` here whenever identity was None, which was
    right while there was no ingestion path and the only way to see retrieval work
    was a canned profile. Once confirmation existed it became a data-corruption
    bug: the demo person arrives `locked`, so the real user's name is refused by
    the L0 lock, and — worse, because it is silent — their employers are *appended*
    next to the fixture's. Memory then holds two people, both confirmed, both
    retrievable as evidence for a cover letter.

    Empty is the honest starting state. `/memory/demo` loads the fixture when a
    demo is what you actually want.
    """
    return STORE


def get_demo_store() -> MemoryStore:
    """The canned profile, loaded on first use.

    For tests that assert on retrieval, ranking, or the attestation deny-list —
    they need a populated profile and do not care whose. Naming it `demo` keeps
    that explicit, so nothing acquires a fixture by accident again.
    """
    if STORE.identity is None:
        STORE.load_fixture()
    return STORE


__all__ = ["MemoryStore", "STORE", "get_store", "get_demo_store", "DEFAULT_FIXTURE"]
