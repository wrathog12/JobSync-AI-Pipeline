"""Does it survive a restart?

Every test here restarts the server for real: a second `TestClient` over a second
lifespan, with a **fresh `MemoryStore`, `DocumentStore` and `CandidateStore`**.
That part is the whole test. Reusing the in-process singletons would make every
assertion pass whether or not a single byte reached disk, which is the easiest way
to ship a persistence layer that persists nothing.

The file lives in `tmp_path` rather than `:memory:` for the same reason — an
in-memory database is private to its connection, so closing it is indistinguishable
from a save that never happened.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from app.llm import FakeClient
from app.memory.store import MemoryStore
from tests.test_structure import RESUME, extracted


@contextmanager
def server(db_file: Path | str, store: MemoryStore, fake: FakeClient | None = None):
    """One server lifetime against `db_file`. Leaving the block is the restart.

    An empty `db_file` means storage off. Note `str(Path(""))` is `"."` — a real,
    truthy, unopenable path — so the falsy check happens before the conversion.
    """
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app import main
    from app.config import get_settings
    from app.ingest.store import DocumentStore
    from app.memory.candidates import CandidateStore

    path = str(db_file) if db_file else ""
    docs, cands = DocumentStore(), CandidateStore()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "get_store", lambda: store)
        mp.setattr(main, "get_documents", lambda: docs)
        mp.setattr(main, "get_candidates", lambda: cands)
        mp.setattr(
            main,
            "get_settings",
            lambda: get_settings().model_copy(update={"db_path": path}),
        )
        if fake is not None:
            mp.setattr(main, "get_client", lambda api_key=None: fake)
        with TestClient(app=main.app) as client:
            yield client


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "jobsync.db"


def ids(candidate: dict) -> list[str]:
    led = candidate["ledger"]
    return [
        r["id"]
        for r in (*led["employment"], *led["education"], *led["projects"], *led["credentials"])
    ]


def ingest_and_confirm(client, **overrides) -> dict:
    """Paste, structure, confirm — the whole write path in one call."""
    doc_id = client.post("/ingest/paste", json={"text": RESUME, "filename": "r.txt"}).json()[
        "doc_id"
    ]
    candidate = client.post(f"/structure/{doc_id}").json()
    body = {
        "doc_id": doc_id,
        "result": candidate,
        "accept_record_ids": ids(candidate),
        "accept_profile_paths": ["email", "phone_e164"],
        "accept_skills": ["Python", "Go"],
        "confirm_identity": True,
        **overrides,
    }
    res = client.post("/confirm", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# ── the point of the exercise ──────────────────────────────────────────────────


def test_a_confirmed_resume_survives_a_restart(db_file):
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        assert ingest_and_confirm(client)["records_committed"] == 4

    after = MemoryStore()
    with server(db_file, after) as client:
        assert client.get("/health").json()["memory_empty"] is False

    assert after.identity is not None
    assert after.identity.full_legal_name() == "Priya Raghunathan"
    assert after.identity.locked is True, "the L0 lock is part of the record, not a session flag"
    assert after.profile.email == "priya.r@example.com"
    assert [e.employer for e in after.ledger.employment] == [
        "Northwind Logistics",
        "Cobalt Systems",
    ], "insertion order is the résumé's order, and reads depend on it"
    assert [s.name for s in after.declared_skills] == ["Python", "Go"]


def test_a_deterministic_field_still_fills_after_a_restart(db_file):
    """The end of the chain. Records on disk are worthless if what was rebuilt from
    them cannot answer the question they exist to answer."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        ingest_and_confirm(client)

    with server(db_file, MemoryStore()) as client:
        trace = client.post(
            "/answer",
            json={"question": "What is your email address?", "field_type": "text"},
        ).json()

    assert trace["abstained"] is False, trace.get("abstain_reason")
    assert "priya.r@example.com" in trace["answer"]


def test_the_derived_layers_are_rebuilt_not_restored(db_file):
    """L3/L4 are never written. If they came back it would be from L2, which is the
    only arrangement where they cannot disagree with their source."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        committed = ingest_and_confirm(client)["evidence_chunks"]
    assert committed > 0

    after = MemoryStore()
    with server(db_file, after):
        pass

    assert len(after.evidence.chunks) == committed
    assert after.graph.competencies, "the competency graph was rebuilt too"

    import sqlite3

    tables = {
        r[0]
        for r in sqlite3.connect(db_file).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert not tables & {"evidence_chunk", "competency", "graph"}


# ── the ways stale rows could come back ────────────────────────────────────────


def test_clearing_memory_stays_cleared(db_file):
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        ingest_and_confirm(client)
        assert client.delete("/memory").json()["memory_empty"] is True

    after = MemoryStore()
    with server(db_file, after) as client:
        assert client.get("/health").json()["memory_empty"] is True
    assert after.is_empty
    assert after.declared_skills == []


def test_clearing_memory_keeps_the_document_and_candidate(db_file):
    """Deliberate: they are staging, not memory, and clearing is usually the prelude
    to re-confirming the same résumé rather than re-uploading it."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        doc_id = client.post("/ingest/paste", json={"text": RESUME}).json()["doc_id"]
        client.post(f"/structure/{doc_id}")
        client.delete("/memory")

    with server(db_file, MemoryStore()) as client:
        assert client.get(f"/ingest/documents/{doc_id}").status_code == 200
        assert client.get(f"/structure/{doc_id}").status_code == 200


def test_loading_the_demo_does_not_leave_the_previous_person_on_disk(db_file):
    """The regression this schema's design note is about.

    `load_fixture` replaces L0-L2 in memory wholesale. An append-only table would
    keep the real user's employment rows, and the next restart would load them next
    to the fixture's — two people, both confirmed, both retrievable as evidence.
    A save mirrors the store, so the old rows go in the same transaction.
    """
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        ingest_and_confirm(client)
        client.post("/memory/demo")

    after = MemoryStore()
    with server(db_file, after):
        pass

    employers = [e.employer for e in after.ledger.employment]
    assert "Northwind Logistics" not in employers, "the real user's records are gone"
    assert employers, "and the fixture's are there"
    assert after.identity.full_legal_name() != "Priya Raghunathan"


def test_a_supersede_persists_without_deleting_the_old_record(db_file):
    """L2's append-only rule is a domain rule, and it has to survive the round trip:
    the superseded record stays on disk, flagged, excluded from retrieval."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        doc_id = client.post("/ingest/paste", json={"text": RESUME}).json()["doc_id"]
        candidate = client.post(f"/structure/{doc_id}").json()
        first, second = (r["id"] for r in candidate["ledger"]["employment"])
        body = client.post(
            "/confirm",
            json={
                "doc_id": doc_id,
                "result": candidate,
                "accept_record_ids": [first, second],
                "supersedes": {second: first},
            },
        ).json()
        assert body["superseded"] == [first]

    after = MemoryStore()
    with server(db_file, after):
        pass

    by_id = {e.id: e for e in after.ledger.employment}
    assert len(by_id) == 2, "nothing was deleted"
    assert by_id[first].superseded_by == second
    assert [e.id for e in after.ledger.active_employment()] == [second]


# ── staging: the expensive thing to lose ───────────────────────────────────────


def test_a_review_in_progress_survives_a_restart_without_paying_again(db_file):
    """A structuring pass costs real money and several seconds. Losing it to a
    restart meant re-running the model over a document that had not changed."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        doc_id = client.post("/ingest/paste", json={"text": RESUME}).json()["doc_id"]
        client.post(f"/structure/{doc_id}")

    after = MemoryStore()
    # An empty script: any LLM call at all raises, so a re-structure would fail here.
    broke = FakeClient([])
    with server(db_file, after, broke) as client:
        candidate = client.get(f"/structure/{doc_id}").json()
        assert candidate["record_count"] == 4
        res = client.post(
            "/confirm",
            json={
                "doc_id": doc_id,
                "result": candidate,
                "accept_record_ids": ids(candidate),
            },
        )

    assert res.status_code == 200
    assert res.json()["records_committed"] == 4
    assert broke.calls == [], "the restored candidate was used, not regenerated"


def test_the_restored_candidate_is_still_the_servers_copy(db_file):
    """The candidate store is authoritative — that is why it exists. A round trip
    through SQLite must not turn it into something the client can overwrite."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        doc_id = client.post("/ingest/paste", json={"text": RESUME}).json()["doc_id"]
        client.post(f"/structure/{doc_id}")

    after = MemoryStore()
    with server(db_file, after) as client:
        candidate = client.get(f"/structure/{doc_id}").json()
        emp = candidate["ledger"]["employment"][0]
        tampered = {**candidate, "ledger": {**candidate["ledger"]}}
        tampered["ledger"]["employment"] = [
            {
                **emp,
                "achievements": [
                    {**emp["achievements"][0], "text": "Personally invented the microservice."}
                ],
            }
        ]
        body = client.post(
            "/confirm",
            json={"doc_id": doc_id, "result": tampered, "accept_record_ids": [emp["id"]]},
        ).json()

    assert body["achievements_user_authored"] == 1
    assert after.ledger.employment[0].provenance.source.value == "user_entered"


def test_a_candidate_whose_document_is_gone_is_not_restored(db_file):
    """`/confirm` fails closed on a missing document — it has no text to verify
    bullets against. Restoring a candidate that can only ever 409 would advertise a
    review the user cannot finish."""
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        doc_id = client.post("/ingest/paste", json={"text": RESUME}).json()["doc_id"]
        client.post(f"/structure/{doc_id}")
        client.delete(f"/ingest/documents/{doc_id}")

    with server(db_file, MemoryStore()) as client:
        assert client.get(f"/structure/{doc_id}").status_code == 404
        assert client.get("/structure").json() == []


# ── configuration and schema mechanics ─────────────────────────────────────────


def test_storage_can_be_turned_off(tmp_path):
    """A supported configuration, not an error — but it says so out loud, because
    "my résumé disappeared" and "storage is off" are otherwise the same symptom."""
    with server("", MemoryStore(), FakeClient([extracted()])) as client:
        health = client.get("/health").json()
        assert health["storage"] is None
        assert ingest_and_confirm(client)["records_committed"] == 4

    assert list(tmp_path.iterdir()) == []


def test_health_reports_what_is_actually_on_disk(db_file):
    with server(db_file, MemoryStore(), FakeClient([extracted()])) as client:
        ingest_and_confirm(client)
        storage = client.get("/health").json()["storage"]

    assert storage["path"] == str(db_file)
    assert storage["ledger_record"] == 4
    assert storage["declared_skill"] == 2
    assert storage["document"] == 1
    assert storage["candidate"] == 1


def test_opening_the_same_file_twice_does_not_rerun_migrations(db_file):
    """`user_version` is the guard. Without it the second open would try to create
    tables that exist and the server would refuse to start."""
    from app.db import MIGRATIONS
    from app.db.connection import close_db, open_db

    db = open_db(str(db_file))
    assert db is not None
    with db.read() as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == len(MIGRATIONS)
    close_db()

    again = open_db(str(db_file))
    assert again is not None
    close_db()


def test_a_second_identity_row_is_impossible(db_file):
    """One database, one person. The CHECK makes a second identity a loud failure
    rather than a second locked name for L0 to defend."""
    import sqlite3

    from app.db.connection import close_db, open_db

    db = open_db(str(db_file))
    assert db is not None
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO identity (id, locked, data, updated_at) VALUES (2, 0, '{}', '')"
            )
    close_db()
