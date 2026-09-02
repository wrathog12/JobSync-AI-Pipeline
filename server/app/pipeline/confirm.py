"""Step 4 — the confirmation pass. The only writer to L0/L1/L2.

Structuring produces candidates; nothing it produces is memory until it comes
through here with explicit per-record consent. That boundary is the same one L6
sessions have, for the same reason: a system that quietly promotes its own guesses
into facts has no way back once a wrong one is committed.

The rule that makes this more than a rubber stamp:

    A bullet the user EDITED is their own words — evidence, and legitimate.
    A bullet they accepted UNCHANGED, which is not in their document, is a
    hallucination they clicked past — and is refused.

Both look identical in the request. Telling them apart requires comparing against
what the model actually produced, which is why the candidate store is
server-authoritative rather than something the client hands back. Without this,
"confirmation" launders exactly the failure the quote check exists to catch: one
click and model prose becomes a permanent fact about someone's career, then serves
as the evidence future claims are grounded against.

Three narrower rules, each closing a specific hole:

* **L2 is append-only.** A correction supersedes; nothing is deleted. Committing
  the same document twice is idempotent because record ids are derived from it.
* **L0 locks on confirm**, and re-confirming needs an explicit unlock. Names and
  citizenship do change; silently overwriting them does not become correct because
  it is convenient.
* **Work authorization and preferences are not confirmable here at all.** They
  never came from the document, so there is nothing to confirm — a request naming
  them is a bug, and gets an error rather than being ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..memory.store import MemoryStore
from ..schemas.common import Confidence, Provenance, Source
from ..schemas.competency import SkillKind, SkillNode
from ..schemas.ledger import Achievement, Employment, LedgerRecord
from ..schemas.profile import Profile
from ..schemas.structured import StructureResult
from ..taxonomy import competencies as comp_tax
from .structure import _is_verbatim, _norm

#: L1 keys a parsed document is allowed to fill. Everything absent from this set
#: is either user-entered by policy (`authorization`) or was never extracted
#: (`preferences`), so naming one is a caller bug worth surfacing.
PROFILE_CONFIRMABLE: frozenset[str] = frozenset({"email", "phone_e164", "location", "links"})


class ConfirmRequest(BaseModel):
    """Per-record consent. Nothing is accepted by omission or by default."""

    doc_id: str
    result: StructureResult = Field(
        description="The candidate set as the user edited it. Compared against the server's copy."
    )
    accept_record_ids: list[str] = Field(
        default_factory=list,
        description="Ledger record ids to commit. Anything not listed is discarded.",
    )
    accept_profile_paths: list[str] = Field(default_factory=list)
    accept_skills: list[str] = Field(default_factory=list)
    confirm_identity: bool = False
    unlock_identity: bool = Field(
        default=False,
        description="Required to overwrite a locked L0. Names change; silent overwrites are not how.",
    )
    supersedes: dict[str, str] = Field(
        default_factory=dict,
        description="New record id -> the existing record it corrects. The old one is kept.",
    )


class Rejection(BaseModel):
    record_id: str
    reason: str
    """User-facing. Says what to do about it."""


class ConfirmResult(BaseModel):
    doc_id: str
    employment_committed: int = 0
    education_committed: int = 0
    projects_committed: int = 0
    credentials_committed: int = 0
    achievements_committed: int = 0
    achievements_user_authored: int = 0
    """Edited by the user, so their words rather than the model's."""
    skills_committed: int = 0
    profile_paths_committed: list[str] = Field(default_factory=list)
    identity_committed: bool = False
    identity_locked: bool = False
    superseded: list[str] = Field(default_factory=list)
    skipped_existing: list[str] = Field(default_factory=list)
    """Already committed by an earlier call. Re-confirming is a no-op, not a duplicate."""
    rejections: list[Rejection] = Field(default_factory=list)
    evidence_chunks: int = 0
    """After the derived rebuild — the point of the whole exercise."""

    @property
    def records_committed(self) -> int:
        return (
            self.employment_committed
            + self.education_committed
            + self.projects_committed
            + self.credentials_committed
        )


def confirm(
    req: ConfirmRequest, candidate: StructureResult, store: MemoryStore, source_text: str
) -> ConfirmResult:
    """Commit what the user accepted. `candidate` is the server's copy, not theirs."""
    if req.doc_id != candidate.doc_id or req.doc_id != req.result.doc_id:
        raise ValueError("doc_id mismatch between the request, its payload, and the candidate")

    out = ConfirmResult(doc_id=req.doc_id)
    now = datetime.now(timezone.utc)
    accepted = set(req.accept_record_ids)
    haystack = _norm(source_text)

    original = _index_records(candidate)
    existing = {r.id for r in _all_records(store)}

    _commit_identity(req, candidate, store, out, now)
    _commit_profile(req, candidate, store, out, now)
    _commit_ledger(req, candidate, store, out, now, accepted, original, existing, haystack)
    _commit_skills(req, store, out)

    if out.records_committed or out.skills_committed:
        # L3 and L4 are derived and disposable; this is the only way they are
        # written, so a commit that skipped it would leave new records
        # unretrievable and the system would abstain on evidence it now has.
        store.rebuild_derived()
    out.evidence_chunks = len(store.evidence.chunks)
    return out


# ── L0 ─────────────────────────────────────────────────────────────────────────


def _commit_identity(
    req: ConfirmRequest,
    candidate: StructureResult,
    store: MemoryStore,
    out: ConfirmResult,
    now: datetime,
) -> None:
    if not req.confirm_identity:
        out.identity_locked = bool(store.identity and store.identity.locked)
        return

    incoming = req.result.identity
    if incoming is None:
        out.rejections.append(
            Rejection(
                record_id="identity",
                reason="No name was submitted, so there is nothing to confirm.",
            )
        )
        return

    if store.identity is not None and store.identity.locked and not req.unlock_identity:
        out.rejections.append(
            Rejection(
                record_id="identity",
                reason=(
                    "Your legal name is already confirmed and locked. Changing it is a "
                    "deliberate action — re-confirm with an unlock if it really changed."
                ),
            )
        )
        out.identity_locked = True
        return

    identity = incoming.model_copy(deep=True)
    identity.provenance = _confirmed(
        now, edited=_differs(incoming, candidate.identity), original_source=Source.PARSED_RESUME
    )
    identity.locked = True
    identity.locked_at = now
    store.identity = identity
    out.identity_committed = True
    out.identity_locked = True


# ── L1 ─────────────────────────────────────────────────────────────────────────


def _commit_profile(
    req: ConfirmRequest,
    candidate: StructureResult,
    store: MemoryStore,
    out: ConfirmResult,
    now: datetime,
) -> None:
    if not req.accept_profile_paths:
        return
    incoming = req.result.profile
    if incoming is None:
        out.rejections.append(
            Rejection(record_id="profile", reason="No contact details were submitted.")
        )
        return

    if store.profile is None:
        # Empty, not a copy of `incoming`: starting from the candidate would commit
        # every parsed field, including the ones the user did not accept.
        store.profile = Profile(
            provenance=_confirmed(now, edited=False, original_source=Source.PARSED_RESUME)
        )

    for path in req.accept_profile_paths:
        if path not in PROFILE_CONFIRMABLE:
            out.rejections.append(
                Rejection(
                    record_id=f"profile.{path}",
                    reason=(
                        f"'{path}' cannot be confirmed from a document. Work authorization "
                        f"and preferences are entered by hand on purpose — a résumé does not "
                        f"state them, and inferring them is how people end up attesting to "
                        f"something untrue."
                    ),
                )
            )
            continue
        setattr(store.profile, path, getattr(incoming, path))
        # Starts the staleness clock for this path. Without it every freshly
        # confirmed field is immediately reported stale.
        store.profile.confirmations[path] = now
        out.profile_paths_committed.append(path)

    if out.profile_paths_committed:
        store.profile.provenance = _confirmed(
            now,
            edited=_differs(incoming, candidate.profile),
            original_source=Source.PARSED_RESUME,
        )


# ── L2 ─────────────────────────────────────────────────────────────────────────


def _commit_ledger(
    req: ConfirmRequest,
    candidate: StructureResult,
    store: MemoryStore,
    out: ConfirmResult,
    now: datetime,
    accepted: set[str],
    original: dict[str, object],
    existing: set[str],
    haystack: str,
) -> None:
    buckets = (
        (req.result.ledger.employment, store.ledger.employment, "employment_committed"),
        (req.result.ledger.education, store.ledger.education, "education_committed"),
        (req.result.ledger.projects, store.ledger.projects, "projects_committed"),
        (req.result.ledger.credentials, store.ledger.credentials, "credentials_committed"),
    )

    for incoming_list, target, counter in buckets:
        for record in incoming_list:
            if record.id not in accepted:
                continue
            if record.id in existing:
                out.skipped_existing.append(record.id)
                continue

            committed = record.model_copy(deep=True)
            committed.provenance = _confirmed(
                now,
                edited=_differs(record, original.get(record.id)),
                original_source=Source.PARSED_RESUME,
            )

            if isinstance(committed, Employment):
                committed.achievements = _confirm_achievements(
                    committed, original.get(record.id), haystack, out
                )

            target.append(committed)
            setattr(out, counter, getattr(out, counter) + 1)
            _apply_supersede(req, record.id, store, out, now)


def _confirm_achievements(
    employment: Employment, original: object, haystack: str, out: ConfirmResult
) -> list[Achievement]:
    """Keep what the user wrote; refuse what they clicked past.

    An edited bullet is the user's own sentence about their own career — the best
    evidence in the system. An unedited bullet that is not in their document is the
    model's invention with a signature on it, and committing it would make the
    grounding check validate future prose against fiction.
    """
    # Keyed on text, not id. Ids are ours and the client has no reason to change
    # them — but if it ever did, an id-keyed check would read every bullet as
    # "edited" and wave the whole document through. The text is what we are
    # actually asking about.
    was = {a.text for a in getattr(original, "achievements", [])}
    kept: list[Achievement] = []

    for ach in employment.achievements:
        edited = ach.text not in was
        if not edited and not _is_verbatim(ach.text, haystack):
            out.rejections.append(
                Rejection(
                    record_id=ach.id,
                    reason=(
                        f'"{ach.text[:70]}" is not in your document and was accepted '
                        f"unchanged, so it is the model's wording rather than yours. Edit it "
                        f"to what you actually did, or leave it out."
                    ),
                )
            )
            continue
        kept.append(ach)
        out.achievements_committed += 1
        if edited:
            out.achievements_user_authored += 1

    return kept


def _apply_supersede(
    req: ConfirmRequest,
    new_id: str,
    store: MemoryStore,
    out: ConfirmResult,
    now: datetime,
) -> None:
    old_id = req.supersedes.get(new_id)
    if not old_id:
        return
    for record in _all_records(store):
        if record.id == old_id:
            # Not deleted. A wrong record that has already been used in an
            # application is part of what was submitted, and that history is the
            # only way to answer "what did I tell them last time".
            record.superseded_by = new_id
            out.superseded.append(old_id)
            return
    out.rejections.append(
        Rejection(
            record_id=new_id,
            reason=f"Cannot supersede '{old_id}' — no such record. The new record was still saved.",
        )
    )


# ── L4 declared skills ─────────────────────────────────────────────────────────


def _commit_skills(req: ConfirmRequest, store: MemoryStore, out: ConfirmResult) -> None:
    have = {s.name.casefold() for s in store.declared_skills}
    for name in req.accept_skills:
        name = name.strip()
        if not name or name.casefold() in have:
            continue

        tag = name.casefold().replace(" ", "_").replace("-", "_")
        if tag in comp_tax.SOFT_COMPETENCIES:
            # The graph's central claim: nobody declares "communication". Everyone
            # would, it is unfalsifiable, and it exists here only as a count of
            # backing evidence. A skills section listing it is not a reason to
            # break that.
            out.rejections.append(
                Rejection(
                    record_id=f"skill.{tag}",
                    reason=(
                        f"'{name}' is a soft skill, so it is not something you can list. It "
                        f"shows up automatically when your achievements demonstrate it — and "
                        f"that version is worth something to an employer."
                    ),
                )
            )
            continue

        store.declared_skills.append(
            SkillNode(id=f"sk_{tag}", name=name, kind=SkillKind.HARD)
        )
        have.add(name.casefold())
        out.skills_committed += 1


# ── helpers ────────────────────────────────────────────────────────────────────


def _confirmed(now: datetime, *, edited: bool, original_source: Source) -> Provenance:
    """USER_STATED, not VERIFIED.

    The user asserting something is the strongest signal we have, but it is not the
    same as checking it against a payslip — and spending VERIFIED on a button click
    would leave nothing to express the stronger case with later.
    """
    return Provenance(
        confidence=Confidence.USER_STATED,
        source=Source.USER_ENTERED if edited else original_source,
        confirmed_at=now,
        updated_at=now,
    )


def _index_records(candidate: StructureResult) -> dict[str, object]:
    return {r.id: r for r in _ledger_records(candidate)}


def _ledger_records(candidate: StructureResult) -> list[LedgerRecord]:
    led = candidate.ledger
    return [*led.employment, *led.education, *led.projects, *led.credentials]


def _all_records(store: MemoryStore) -> list[LedgerRecord]:
    led = store.ledger
    return [*led.employment, *led.education, *led.projects, *led.credentials]


def _differs(submitted: object, original: object) -> bool:
    """Did the user change anything? Provenance is excluded — we set that."""
    if original is None:
        return True
    a = _comparable(submitted)
    b = _comparable(original)
    return a != b


def _comparable(record: object) -> dict:
    if not isinstance(record, BaseModel):
        return {}
    return record.model_dump(mode="json", exclude={"provenance", "superseded_by"})


__all__ = [
    "ConfirmRequest",
    "ConfirmResult",
    "Rejection",
    "confirm",
    "PROFILE_CONFIRMABLE",
]
