"""Hand edits to memory — the second writer to L0/L1/L2, and the one the user drives.

`confirm.py` commits what a *document* said. This commits what the *user* says,
when the document was wrong, out of date, or silent about it. Everything between
those two was missing: the API could add records and wipe all of memory, and
nothing in between, so one misread job title could only be fixed by clearing
everything and uploading the résumé again.

Two rules carry over unchanged, because they are why any of this is trustworthy.

**A record is never edited in place.** An edit appends a corrected copy and points
the old one at it. The old record stays — flagged, and out of retrieval — because
it is part of what was already submitted in an application, and keeping it is the
only way to answer "what did I tell them last time". `confirm.py` calls this
superseding; a hand edit is the same operation with a person behind it instead of
a document.

**An edited bullet is the user's own words**, so it is stored as `USER_ENTERED`
and the verbatim check does not apply to it. That is not a hole in the guard: the
guard exists to catch *model* prose accepted unchanged. A sentence someone typed
about their own career is the best evidence in the system, and refusing it would
mean their memory could only ever hold what a parser happened to read correctly.

Retraction is a third state rather than a delete, for the same audit reason —
`retracted_at` takes a record out of retrieval and leaves it on disk.

One thing this module deliberately *can* write that `confirm.py` refuses:
**work authorization and preferences**. A résumé does not state them, which is why
confirming them from a document is a bug — but they have to be enterable
somewhere, and by hand is the only honest way in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ..memory.store import MemoryStore
from ..schemas.common import Confidence, Provenance, Source
from ..schemas.competency import SkillKind, SkillNode
from ..schemas.identity import Identity
from ..schemas.ledger import (
    Achievement,
    Credential,
    Education,
    Employment,
    EmploymentType,
    LedgerRecord,
    Project,
)
from ..schemas.profile import Links, Location, Preferences, Profile, WorkAuthorization
from ..taxonomy import competencies as comp_tax
from .structure import _metrics


class EditError(Exception):
    """A refusal the user should read. `status` is the HTTP code it becomes.

    The message is the whole value here — "409" tells someone nothing, "your legal
    name is locked, unlock it if it really changed" tells them what to do.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ── L2: one record at a time ───────────────────────────────────────────────────


class RecordPatch(BaseModel):
    """Only the fields being changed. Absent and `null` are different.

    `null` means "clear this" — a GPA the user wants gone, or an end date removed
    because the job is current. Absent means "leave it alone". Pydantic's
    `model_fields_set` is what tells them apart, so nothing here may be read with
    a plain truthiness check.
    """

    model_config = ConfigDict(extra="forbid")

    # employment
    employer: str | None = None
    title: str | None = None
    employment_type: EmploymentType | None = None
    location: str | None = None
    summary: str | None = None
    achievements: list[str] | None = None
    # education
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    gpa: float | None = None
    honors: list[str] | None = None
    # project
    name: str | None = None
    role: str | None = None
    url: str | None = None
    # credential
    issuer: str | None = None
    issued: str | None = None
    expires: str | None = None
    credential_id: str | None = None
    # shared, and flattened out of `dates` because a form has two date inputs and
    # no reason to know DateRange exists
    start: str | None = None
    end: str | None = None


#: What each kind of record will accept. Naming a field the record does not have is
#: an error rather than a silent no-op: a UI sending `gpa` to an employment record
#: has a bug, and swallowing it means the user watches their edit vanish.
EDITABLE: dict[type, frozenset[str]] = {
    Employment: frozenset(
        {"employer", "title", "employment_type", "location", "summary", "achievements", "start", "end"}
    ),
    Education: frozenset(
        {"institution", "degree", "field_of_study", "gpa", "honors", "start", "end"}
    ),
    Project: frozenset({"name", "role", "summary", "url", "start", "end"}),
    Credential: frozenset({"name", "issuer", "issued", "expires", "credential_id"}),
}

#: Fields that cannot be blanked. A record with no employer is not a correction,
#: it is a record nothing can ever match — and it would still be retrievable.
REQUIRED: dict[type, frozenset[str]] = {
    Employment: frozenset({"employer", "title"}),
    Education: frozenset({"institution", "degree"}),
    Project: frozenset({"name"}),
    Credential: frozenset({"name", "issuer"}),
}

KIND_LABEL: dict[type, str] = {
    Employment: "job",
    Education: "education",
    Project: "project",
    Credential: "credential",
}


def edit_record(
    record_id: str, patch: RecordPatch, store: MemoryStore
) -> tuple[LedgerRecord, LedgerRecord]:
    """Supersede `record_id` with a corrected copy. Returns (old, new)."""
    old = _find(store, record_id)
    if not old.is_active:
        raise EditError(
            "that record has already been superseded or removed — edit the one that replaced it",
            status=409,
        )

    changed = patch.model_fields_set
    if not changed:
        raise EditError("nothing to change")

    kind = type(old)
    unknown = sorted(changed - EDITABLE[kind])
    if unknown:
        raise EditError(f"a {KIND_LABEL[kind]} record has no {', '.join(unknown)}")

    now = datetime.now(timezone.utc)
    new = old.model_copy(deep=True)
    new.id = _new_id(old.id)
    new.superseded_by = None
    new.retracted_at = None
    new.provenance = _by_hand(now)

    for key in changed:
        value = getattr(patch, key)
        if key in ("start", "end"):
            setattr(new.dates, key, _clean(value))
            continue
        if key == "achievements":
            new.achievements = _rewrite_achievements(old, value or [])
            continue
        if isinstance(value, str) or value is None:
            value = _clean(value)
        if key in REQUIRED[kind] and not value:
            raise EditError(f"{key} cannot be empty on a {KIND_LABEL[kind]} record")
        setattr(new, key, value)

    old.superseded_by = new.id
    # Directly after the record it replaces, not appended. Insertion order *is* the
    # résumé's order — `load_memory` reloads by it and "my last two jobs" reads it —
    # so appending would quietly move a corrected job to the bottom of the history.
    bucket = _bucket(store, new)
    bucket.insert(bucket.index(old) + 1, new)
    # L3 and L4 come from L2, so an edit that skipped this would leave retrieval
    # citing the old wording while the page shows the new one.
    store.rebuild_derived()
    return old, new


def retract_record(record_id: str, store: MemoryStore) -> LedgerRecord:
    """Take a record out of retrieval without deleting it.

    Not a delete, and not a supersede either — there is no replacement. The user
    is saying "this is not part of my history", usually because the parser invented
    a job out of a reference or a course listing. It stays on disk because an
    application already sent somewhere may have been built on it.
    """
    record = _find(store, record_id)
    if not record.is_active:
        raise EditError("that record is already superseded or removed", status=409)
    record.retracted_at = datetime.now(timezone.utc)
    store.rebuild_derived()
    return record


def _rewrite_achievements(old: LedgerRecord, texts: list[str]) -> list[Achievement]:
    """Replace the bullet list, keeping the bullets that did not change.

    Matched on text rather than id, because the client has no reason to send ids
    back and a retyped bullet is a different sentence regardless of what id it
    arrived with. An unchanged bullet keeps its id, its metrics and its skill
    links; a retyped one loses the skill links, since those came from the model
    reading the *previous* sentence and re-using them would attribute a skill to
    words that no longer claim it.
    """
    was = {a.text: a for a in getattr(old, "achievements", [])}
    out: list[Achievement] = []
    for text in texts:
        text = text.strip()
        if not text:
            continue
        kept = was.get(text)
        out.append(
            kept.model_copy(deep=True)
            if kept is not None
            else Achievement(id=f"ach_{uuid4().hex[:8]}", text=text, metrics=_metrics(text))
        )
    return out


# ── L1: profile ────────────────────────────────────────────────────────────────


class ProfilePatch(BaseModel):
    """Contact details, links, authorization and preferences. All hand-entered."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    phone_e164: str | None = None
    location: Location | None = None
    links: Links | None = None
    authorization: WorkAuthorization | None = None
    preferences: Preferences | None = None


#: Sending `null` for one of these means "reset it", not "make it None" — they are
#: sub-objects with defaults, and `None` would leave `profile.location.city` a
#: crash instead of a blank.
_PROFILE_DEFAULTS: dict[str, type] = {
    "location": Location,
    "links": Links,
    "authorization": WorkAuthorization,
    "preferences": Preferences,
}


def edit_profile(patch: ProfilePatch, store: MemoryStore) -> Profile:
    changed = patch.model_fields_set
    if not changed:
        raise EditError("nothing to change")

    now = datetime.now(timezone.utc)
    if store.profile is None:
        store.profile = Profile(provenance=_by_hand(now))

    for key in changed:
        value = getattr(patch, key)
        if value is None and key in _PROFILE_DEFAULTS:
            value = _PROFILE_DEFAULTS[key]()
        elif isinstance(value, str) or value is None:
            value = _clean(value)
        if key == "authorization" and isinstance(value, WorkAuthorization):
            # The user typing it *is* the confirmation. Without this stamp the
            # staleness prompt fires immediately on a field just filled in.
            value.confirmed_at = now
            value.source = Source.USER_ENTERED
        setattr(store.profile, key, value)
        store.profile.confirmations[key] = now

    store.profile.provenance = _by_hand(now)
    return store.profile


# ── L0: identity ───────────────────────────────────────────────────────────────


class IdentityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_first: str | None = None
    legal_middle: str | None = None
    legal_last: str | None = None
    preferred_name: str | None = None
    date_of_birth: str | None = None
    citizenship: list[str] | None = None
    pronouns: str | None = None


def edit_identity(patch: IdentityPatch, store: MemoryStore, *, unlock: bool = False) -> Identity:
    """Set or correct the legal name. Locked afterwards, as `confirm.py` leaves it.

    The lock is the point: names and citizenship do change, and the flow for that
    is an explicit unlock rather than a quiet overwrite from whatever the last
    document happened to say.
    """
    changed = patch.model_fields_set
    if not changed:
        raise EditError("nothing to change")

    now = datetime.now(timezone.utc)
    if store.identity is None:
        first, last = _clean(patch.legal_first), _clean(patch.legal_last)
        if not first or not last:
            raise EditError("a first and last legal name are needed to start an identity")
        store.identity = Identity(
            legal_first=first, legal_last=last, provenance=_by_hand(now), locked=True, locked_at=now
        )
        changed = changed - {"legal_first", "legal_last"}
    elif store.identity.locked and not unlock:
        raise EditError(
            "your legal name is confirmed and locked. Changing it is deliberate — "
            "send unlock=true if it really changed.",
            status=409,
        )

    for key in changed:
        value = getattr(patch, key)
        if isinstance(value, str) or value is None:
            value = _clean(value)
        if key in ("legal_first", "legal_last") and not value:
            raise EditError(f"{key} cannot be empty")
        setattr(store.identity, key, value if value is not None else _identity_blank(key))

    store.identity.provenance = _by_hand(now)
    store.identity.locked = True
    store.identity.locked_at = store.identity.locked_at or now
    return store.identity


def _identity_blank(key: str) -> object:
    return [] if key == "citizenship" else None


# ── L4: declared skills ────────────────────────────────────────────────────────


def add_skill(name: str, store: MemoryStore) -> SkillNode:
    name = (name or "").strip()
    if not name:
        raise EditError("a skill needs a name")
    if any(s.name.casefold() == name.casefold() for s in store.declared_skills):
        raise EditError(f"'{name}' is already listed", status=409)

    tag = name.casefold().replace(" ", "_").replace("-", "_")
    if tag in comp_tax.SOFT_COMPETENCIES:
        # Same refusal as `confirm.py`, for the same reason: everyone would list
        # "communication", it is unfalsifiable, and the graph already reports it
        # from the achievements that demonstrate it — which is the version worth
        # something to an employer.
        raise EditError(
            f"'{name}' is a soft skill, so it is not something you list. It appears on its own "
            f"when your achievements demonstrate it."
        )

    skill = SkillNode(id=f"sk_{tag}", name=name, kind=SkillKind.HARD)
    store.declared_skills.append(skill)
    store.rebuild_derived()
    return skill


def rename_skill(skill_id: str, name: str, store: MemoryStore) -> SkillNode:
    """Fix a typo. The id stays put on purpose — achievements point at it.

    A typo'd skill is the quiet failure: retrieval is keyword-based, so `Pyhton`
    silently stops matching a job description's `Python` and the damage is
    invisibility rather than a visible misspelling.
    """
    name = (name or "").strip()
    if not name:
        raise EditError("a skill needs a name")
    skill = next((s for s in store.declared_skills if s.id == skill_id), None)
    if skill is None:
        raise EditError(f"no skill '{skill_id}'", status=404)
    skill.name = name
    store.rebuild_derived()
    return skill


def remove_skill(skill_id: str, store: MemoryStore) -> SkillNode:
    skill = next((s for s in store.declared_skills if s.id == skill_id), None)
    if skill is None:
        raise EditError(f"no skill '{skill_id}'", status=404)
    store.declared_skills.remove(skill)
    store.rebuild_derived()
    return skill


# ── helpers ────────────────────────────────────────────────────────────────────


def _by_hand(now: datetime) -> Provenance:
    """USER_STATED and USER_ENTERED: the user typed it, which is the strongest
    signal available short of checking it against a payslip."""
    return Provenance(
        confidence=Confidence.USER_STATED,
        source=Source.USER_ENTERED,
        confirmed_at=now,
        updated_at=now,
    )


def _clean(value: str | None) -> str | None:
    """Whitespace-only means "not stated", which is not an empty value on purpose."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _new_id(old_id: str) -> str:
    """Keeps the family prefix, so an id still says what it is at a glance.

    The rest is random rather than derived: an edit has no document behind it to
    take a stable seed from, and two edits of the same record must not collide.
    """
    prefix = old_id.split("_", 1)[0] if "_" in old_id else "rec"
    return f"{prefix}_{uuid4().hex[:8]}"


def _all_records(store: MemoryStore) -> list[LedgerRecord]:
    led = store.ledger
    return [*led.employment, *led.education, *led.projects, *led.credentials]


def _find(store: MemoryStore, record_id: str) -> LedgerRecord:
    record = next((r for r in _all_records(store) if r.id == record_id), None)
    if record is None:
        raise EditError(f"no record '{record_id}'", status=404)
    return record


def _bucket(store: MemoryStore, record: LedgerRecord) -> list:
    led = store.ledger
    return {
        Employment: led.employment,
        Education: led.education,
        Project: led.projects,
        Credential: led.credentials,
    }[type(record)]


__all__ = [
    "EditError",
    "RecordPatch",
    "ProfilePatch",
    "IdentityPatch",
    "edit_record",
    "retract_record",
    "edit_profile",
    "edit_identity",
    "add_skill",
    "rename_skill",
    "remove_skill",
    "EDITABLE",
]
