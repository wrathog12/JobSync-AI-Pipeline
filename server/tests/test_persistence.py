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
    from app.memory.sessions import SessionStore

    path = str(db_file) if db_file else ""
    docs, cands = DocumentStore(), CandidateStore()
    # A fresh SessionStore as well, for the same reason as the others: the module
    # singleton would carry live sessions across the "restart" and every assertion
    # about L6 surviving would pass without a byte reaching disk.
    sessions = SessionStore()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "get_store", lambda: store)
        mp.setattr(main, "get_documents", lambda: docs)
        mp.setattr(main, "get_candidates", lambda: cands)
        mp.setattr(main, "get_sessions", lambda: sessions)
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


# ── L6: the application in progress ────────────────────────────────────────────
#
# Sessions are not memory and are never merged into it. What a restart used to
# destroy here was the user's *work*: the description they pasted by hand, every
# answer already given, and the spent-evidence ledger that stops page 6 retelling
# page 2's story. A Workday application is filled over half an hour, and this was
# the only thing in the system the user could not cheaply redo.


JD = (
    "Staff Backend Engineer. You will own the ingestion pipeline end to end, from "
    "parsing uploaded documents through to the retrieval layer. Required: five "
    "years of Python and production experience with retrieval systems."
)


def open_session(client, **kw) -> str:
    res = client.post("/sessions", json={"mode": "strict", **kw})
    assert res.status_code == 200, res.text
    return res.json()["session_id"]


def test_a_pasted_job_description_survives_a_restart(db_file):
    """The one piece of session state that cannot be recovered from the page. On a
    Workday wizard the posting is out of the DOM by page 4, so if this is lost the
    user has to go and find the advert again mid-application."""
    with server(db_file, MemoryStore()) as client:
        session_id = open_session(client, company="Northwind Labs")
        res = client.post(f"/sessions/{session_id}/jd", json={"jd_text": JD})
        fingerprint = res.json()["jd_fingerprint"]

    with server(db_file, MemoryStore()) as client:
        session = client.get(f"/sessions/{session_id}").json()

    assert session["jd_text"] == JD
    assert session["company"] == "Northwind Labs"
    assert session["jd_fingerprint"] == fingerprint, (
        "the fingerprint is how the extension reattaches after navigation — "
        "a different one after a restart is a session the page can no longer find"
    )


def test_the_page_number_and_the_answers_already_given_come_back(db_file):
    """Answering the same question twice is not harmless: the second answer is
    written without knowing the first exists, so a two-page form can contradict
    itself in the user's own words."""
    with server(db_file, MemoryStore()) as client:
        session_id = open_session(client, jd_text=JD)
        client.post(
            "/answer",
            json={
                "question": "Why do you want this role?",
                "field_type": "textarea",
                "session_id": session_id,
            },
        )
        client.post(f"/sessions/{session_id}/next-page", params={"page_url": "https://x/page2"})

    with server(db_file, MemoryStore()) as client:
        session = client.get(f"/sessions/{session_id}").json()

    assert session["page_index"] == 1
    assert session["pages_seen"] == ["https://x/page2"]
    assert [a["question"] for a in session["answered"]] == ["Why do you want this role?"]


def test_spent_evidence_survives_so_a_later_page_does_not_repeat_itself(db_file):
    """`spent_chunks` is what makes page 6 tell a different story from page 2. It
    is a counter, and a counter that resets is worse than no counter: the user
    watches the same achievement come back in the answer they thought was new."""
    from app.schemas.session import AnsweredField, field_key

    with server(db_file, MemoryStore()) as client:
        from app import main

        session_id = open_session(client, jd_text=JD)
        main.get_sessions().get(session_id).record(
            AnsweredField(
                field_key=field_key("Tell us about a project."),
                question="Tell us about a project.",
                answer="I rebuilt the ingestion pipeline.",
                mode="strict",
                trace_id="tr_test",
                used_chunks=["ev_pipeline", "ev_python"],
            )
        )
        # A write to the session object alone reaches nothing; an endpoint has to
        # save it. That is exactly the coupling this test is here to hold.
        client.post(f"/sessions/{session_id}/next-page")

    with server(db_file, MemoryStore()) as client:
        session = client.get(f"/sessions/{session_id}").json()

    assert session["spent_chunks"] == {"ev_pipeline": 1, "ev_python": 1}


def test_a_dropped_session_does_not_come_back(db_file):
    """The user closing an application means it is finished with. A restart that
    resurrects it puts a stale JD back in front of the next one they open."""
    with server(db_file, MemoryStore()) as client:
        session_id = open_session(client, jd_text=JD)
        assert client.delete(f"/sessions/{session_id}").json()["dropped"] is True

    with server(db_file, MemoryStore()) as client:
        assert client.get(f"/sessions/{session_id}").status_code == 404
        assert client.get("/sessions").json() == []


def test_the_order_sessions_were_started_in_survives(db_file):
    """The store evicts the oldest when it is full. Loading them back in a
    different order would make a restart quietly discard the wrong application."""
    with server(db_file, MemoryStore()) as client:
        first = open_session(client, company="First")
        second = open_session(client, company="Second")
        third = open_session(client, company="Third")

    with server(db_file, MemoryStore()) as client:
        listed = [s["session_id"] for s in client.get("/sessions").json()]

    assert listed == [third, second, first], "newest first, as it was before the restart"


def test_health_counts_the_sessions_on_disk(db_file):
    with server(db_file, MemoryStore()) as client:
        open_session(client, jd_text=JD)
        open_session(client)
        assert client.get("/health").json()["storage"]["session"] == 2


def test_sessions_still_work_with_storage_off(tmp_path):
    """Storage off is a supported configuration. Sessions are the layer most likely
    to be exercised in it, since it is the one that needs no uploaded documents."""
    with server("", MemoryStore()) as client:
        session_id = open_session(client, jd_text=JD)
        assert client.get(f"/sessions/{session_id}").json()["jd_text"] == JD
    assert list(tmp_path.iterdir()) == []
