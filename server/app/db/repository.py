"""Reading and writing the layers. The only module that knows SQL exists.

`MemoryStore` is still the source of truth in-process; this mirrors it to disk.
The direction matters: **a save makes the database match the store exactly**,
including deleting ledger rows the store no longer holds.

That is a deliberate departure from L2's append-only rule, and it is the safer
choice. L2 is append-only in the *domain* — `confirm.py` supersedes and never
deletes, which is where that invariant belongs and where it is tested. Letting the
database keep rows the store has dropped would only add a way for the two to
disagree, and the failure mode is specific and already familiar: load the demo
fixture, which replaces L0-L2 wholesale, and an append-only table would keep the
previous person's employment rows. A restart then resurrects them next to the
real ones — two people in memory, both confirmed, both retrievable. That is the
exact bug `get_store()` was fixed for, arriving through a different door.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..memory.candidates import CandidateStore
from ..memory.store import MemoryStore
from ..schemas.answer_memory import AnswerMemory, ApprovedAnswer
from ..schemas.competency import SkillNode
from ..schemas.identity import Identity
from ..schemas.ingest import RawDocument
from ..schemas.ledger import Credential, Education, Employment, Project
from ..schemas.profile import Profile
from ..schemas.structured import StructureResult
from .connection import Database

#: `kind` column value -> (model, the `Ledger` attribute it lives on).
_LEDGER_KINDS: dict[str, tuple[type, str]] = {
    "employment": (Employment, "employment"),
    "education": (Education, "education"),
    "project": (Project, "projects"),
    "credential": (Credential, "credentials"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── memory: L0, L1, L2, L4-declared, L5 ────────────────────────────────────────


def load_memory(store: MemoryStore, db: Database) -> bool:
    """Fill an empty store from disk. Returns whether anything was there.

    Loads into the store the caller passes rather than the module singleton, so a
    test can hand over its own and the production path stays the same code.
    """
    with db.read() as conn:
        row = conn.execute("SELECT data FROM identity WHERE id = 1").fetchone()
        store.identity = Identity.model_validate_json(row["data"]) if row else None

        row = conn.execute("SELECT data FROM profile WHERE id = 1").fetchone()
        store.profile = Profile.model_validate_json(row["data"]) if row else None

        # Insertion order, because L2 is a history and "my last two jobs" reads it
        # in the order the résumé listed them.
        rows = conn.execute(
            "SELECT kind, data FROM ledger_record ORDER BY created_at, rowid"
        ).fetchall()
        for r in rows:
            model, attr = _LEDGER_KINDS[r["kind"]]
            getattr(store.ledger, attr).append(model.model_validate_json(r["data"]))

        rows = conn.execute("SELECT data FROM declared_skill ORDER BY rowid").fetchall()
        store.declared_skills = [SkillNode.model_validate_json(r["data"]) for r in rows]

        rows = conn.execute(
            "SELECT data FROM approved_answer ORDER BY approved_at, rowid"
        ).fetchall()
        store.answers = AnswerMemory(
            answers=[ApprovedAnswer.model_validate_json(r["data"]) for r in rows]
        )

    if store.is_empty and not store.declared_skills and not store.answers.answers:
        return False
    # L3 and L4 were never stored. Rebuilding them here is what makes a restart
    # invisible: without it the store holds records that nothing can retrieve.
    store.rebuild_derived()
    return True


def save_memory(store: MemoryStore, db: Database) -> None:
    """Mirror the store to disk in one transaction."""
    now = _now()
    with db.tx() as conn:
        if store.identity is None:
            conn.execute("DELETE FROM identity")
        else:
            conn.execute(
                "INSERT INTO identity (id, locked, data, updated_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET locked = excluded.locked, "
                "data = excluded.data, updated_at = excluded.updated_at",
                (int(store.identity.locked), store.identity.model_dump_json(), now),
            )

        if store.profile is None:
            conn.execute("DELETE FROM profile")
        else:
            conn.execute(
                "INSERT INTO profile (id, data, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
                "updated_at = excluded.updated_at",
                (store.profile.model_dump_json(), now),
            )

        keep: list[str] = []
        for kind, (_, attr) in _LEDGER_KINDS.items():
            for record in getattr(store.ledger, attr):
                keep.append(record.id)
                conn.execute(
                    "INSERT INTO ledger_record (id, kind, superseded_by, data, created_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    # created_at is left alone: it records when the record first
                    # reached the ledger, and a later supersede must not restamp it.
                    "ON CONFLICT(id) DO UPDATE SET superseded_by = excluded.superseded_by, "
                    "data = excluded.data",
                    (record.id, kind, record.superseded_by, record.model_dump_json(), now),
                )
        _prune(conn, "ledger_record", "id", keep)

        skills = [s.id for s in store.declared_skills]
        for skill in store.declared_skills:
            conn.execute(
                "INSERT INTO declared_skill (id, name, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, data = excluded.data",
                (skill.id, skill.name, skill.model_dump_json()),
            )
        _prune(conn, "declared_skill", "id", skills)

        answers = [a.id for a in store.answers.answers]
        for ans in store.answers.answers:
            conn.execute(
                "INSERT INTO approved_answer "
                "(id, canonical_question_id, company_id, data, approved_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (
                    ans.id,
                    ans.canonical_question_id,
                    ans.company_id,
                    ans.model_dump_json(),
                    ans.approved_at.isoformat(),
                ),
            )
        _prune(conn, "approved_answer", "id", answers)


def _prune(conn, table: str, key: str, keep: list[str]) -> None:  # noqa: ANN001
    """Delete rows the store no longer holds.

    The id list is spliced in as literals via bound parameters, not formatted —
    only the table and key names are interpolated, and both are module constants.
    """
    if not keep:
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 — constant identifier
        return
    marks = ",".join("?" * len(keep))
    conn.execute(f"DELETE FROM {table} WHERE {key} NOT IN ({marks})", keep)  # noqa: S608


def wipe_memory(db: Database) -> None:
    """Erase the stored layers. Staged documents and candidates survive.

    They are not memory, and a user clearing a half-confirmed profile almost always
    wants to re-review the same résumé rather than re-upload and re-pay for it.
    """
    with db.tx() as conn:
        for table in ("identity", "profile", "ledger_record", "declared_skill", "approved_answer"):
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 — constant identifier


# ── staging: documents and candidates ──────────────────────────────────────────


def save_document(doc: RawDocument, db: Database) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO document (doc_id, data, created_at) VALUES (?, ?, ?) "
            # Documents are keyed by content hash, so a conflict means the identical
            # bytes arrived twice. The first extraction wins, matching DocumentStore.
            "ON CONFLICT(doc_id) DO NOTHING",
            (doc.doc_id, doc.model_dump_json(), doc.extracted_at.isoformat()),
        )


def delete_document(doc_id: str, db: Database) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM document WHERE doc_id = ?", (doc_id,))


def save_candidate(result: StructureResult, db: Database) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO candidate (doc_id, data, created_at) VALUES (?, ?, ?) "
            # Latest wins, matching CandidateStore: re-structuring is a deliberate
            # retry and the newer reading is the one the user is reviewing.
            "ON CONFLICT(doc_id) DO UPDATE SET data = excluded.data, "
            "created_at = excluded.created_at",
            (result.doc_id, result.model_dump_json(), _now()),
        )


def delete_candidate(doc_id: str, db: Database) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM candidate WHERE doc_id = ?", (doc_id,))


def load_staging(documents, candidates: CandidateStore, db: Database) -> None:  # noqa: ANN001
    """Restore the review in progress.

    A candidate whose document is missing is dropped rather than loaded: `/confirm`
    would refuse it anyway (no source text means no verbatim check, so it fails
    closed with a 409), and offering a reviewable candidate that cannot be
    committed is a worse experience than offering none.
    """
    with db.read() as conn:
        for row in conn.execute("SELECT data FROM document ORDER BY created_at").fetchall():
            documents.put(RawDocument.model_validate_json(row["data"]))
        for row in conn.execute("SELECT data FROM candidate ORDER BY created_at").fetchall():
            result = StructureResult.model_validate_json(row["data"])
            if documents.get(result.doc_id) is not None:
                candidates.put(result)


def load_all(store: MemoryStore, documents, candidates: CandidateStore, db: Database) -> bool:  # noqa: ANN001
    """Everything, at startup. Returns whether stored memory was found."""
    found = load_memory(store, db)
    load_staging(documents, candidates, db)
    return found


def stats(db: Database) -> dict:
    """What is actually on disk, for `/health`. Cheap enough to call per request."""
    with db.read() as conn:
        counts = {
            table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in ("ledger_record", "declared_skill", "approved_answer", "document", "candidate")
        }
    return {"path": db.path, **counts}


__all__ = [
    "load_memory",
    "save_memory",
    "wipe_memory",
    "save_document",
    "delete_document",
    "save_candidate",
    "delete_candidate",
    "load_staging",
    "load_all",
    "stats",
]
