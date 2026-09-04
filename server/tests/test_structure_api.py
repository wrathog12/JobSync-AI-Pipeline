"""HTTP tests for steps 3 and 4.

Deliberately thin on pipeline behaviour — `test_structure.py` and
`test_confirm.py` own that. What is only testable here is the wiring, and one
piece of it carries the whole design:

    `/confirm` reads the candidate and the source text from the server's own
    stores, never from the request body.

If either came from the client, "did the user edit this bullet or rubber-stamp
the model's invention" would be a question the client answers about itself.
`test_the_servers_candidate_wins_over_the_clients` is the one that pins it.

Also here: the blame-to-status-code mapping, because a mistyped API key arriving
as a 502 sends the user to our status page instead of to their key.
"""

from __future__ import annotations

import pytest

from app.llm import FakeClient, LLMAuthError, LLMProviderError, LLMQuotaError
from app.memory.store import MemoryStore
from tests.test_structure import RESUME, extracted


@pytest.fixture
def store() -> MemoryStore:
    """A blank store. `/confirm` writes for real, and the fixture profile is a
    different person — committing into it would make every assertion ambiguous."""
    return MemoryStore()


@pytest.fixture
def client(monkeypatch, store):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app import main
    from app.ingest.store import get_documents
    from app.memory.candidates import get_candidates

    monkeypatch.setattr(main, "get_store", lambda: store)
    get_documents().clear()
    get_candidates().clear()
    with TestClient(app=main.app) as c:
        yield c
    get_documents().clear()
    get_candidates().clear()


def script(client, monkeypatch, *responses) -> FakeClient:
    """Point the endpoint at a scripted model. Returns the fake, so a test can
    assert on the prompt that was actually sent."""
    from app import main

    fake = FakeClient(responses)
    monkeypatch.setattr(main, "get_client", lambda api_key=None: fake)
    return fake


def upload(client, text: str = RESUME) -> str:
    res = client.post("/ingest/paste", json={"text": text, "filename": "resume.txt"})
    assert res.status_code == 200
    return res.json()["doc_id"]


# ── POST /structure ────────────────────────────────────────────────────────────


def test_structuring_returns_candidates_and_counts(client, monkeypatch):
    doc_id = upload(client)
    fake = script(client, monkeypatch, extracted())

    res = client.post(f"/structure/{doc_id}")
    assert res.status_code == 200
    body = res.json()

    assert body["doc_id"] == doc_id
    assert body["record_count"] == 4
    assert body["achievement_count"] == 3
    assert body["unverified_quotes"] == 0
    assert len(body["ledger"]["employment"]) == 2
    assert body["identity"]["legal_first"] == "Priya"
    # The document text goes in the user turn, the rules in the system turn.
    assert "Northwind" in fake.last.prompt
    assert "COPY, DO NOT WRITE" in (fake.last.system or "")


def test_structuring_writes_nothing_to_memory(client, monkeypatch, store):
    """The whole point of a separate confirmation step. Structuring produces a
    proposal; a proposal that had already been saved is not one."""
    doc_id = upload(client)
    script(client, monkeypatch, extracted())
    client.post(f"/structure/{doc_id}")

    assert store.identity is None
    assert store.profile is None
    assert store.ledger.employment == []
    assert store.evidence.chunks == []


def test_the_candidate_is_retrievable_afterwards(client, monkeypatch):
    """The review UI reloads, and re-running the model to redraw a page would cost
    money for a document that has not changed."""
    doc_id = upload(client)
    script(client, monkeypatch, extracted())
    posted = client.post(f"/structure/{doc_id}").json()

    got = client.get(f"/structure/{doc_id}")
    assert got.status_code == 200
    assert got.json()["ledger"] == posted["ledger"]
    assert [s["doc_id"] for s in client.get("/structure").json()] == [doc_id]


def test_restructuring_replaces_the_candidate(client, monkeypatch):
    """A retry with a different prompt or model is deliberate, and the newer
    reading is the one the user is looking at."""
    doc_id = upload(client)
    script(client, monkeypatch, extracted(), extracted(employment=[]))

    assert client.post(f"/structure/{doc_id}").json()["record_count"] == 4
    assert client.post(f"/structure/{doc_id}").json()["record_count"] == 2
    assert client.get(f"/structure/{doc_id}").json()["record_count"] == 2


def test_an_unknown_document_is_404(client, monkeypatch):
    script(client, monkeypatch, extracted())
    assert client.post("/structure/doc_nope").status_code == 404


def test_an_unusable_document_is_refused_before_the_model_is_paid(client, monkeypatch):
    """422, not 500: the upload worked and the user has a real next step. And no
    LLM call — a scan with no text layer cannot be structured, and charging for
    the attempt is worse than saying so."""
    doc_id = upload(client, text="Priya R.")
    fake = script(client, monkeypatch)  # empty script: any call raises

    res = client.post(f"/structure/{doc_id}")
    assert res.status_code == 422
    assert fake.calls == []


def test_a_candidate_can_be_discarded_without_losing_the_document(client, monkeypatch):
    doc_id = upload(client)
    script(client, monkeypatch, extracted())
    client.post(f"/structure/{doc_id}")

    assert client.delete(f"/structure/{doc_id}").json() == {"dropped": True}
    assert client.get(f"/structure/{doc_id}").status_code == 404
    assert client.get(f"/ingest/documents/{doc_id}").status_code == 200


# ── blame decides the status code ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "status", "blame"),
    [
        (LLMAuthError("bad key"), 400, "user_key"),
        (LLMQuotaError("out of quota"), 429, "user_key"),
        (LLMProviderError("gemini is down"), 502, "provider"),
    ],
)
def test_the_status_code_says_who_has_to_act(client, monkeypatch, error, status, blame):
    """A client branches on the status before it reads the body. Quota is 429
    rather than 400 because the answer is to wait, not to re-enter a key."""
    doc_id = upload(client)
    script(client, monkeypatch, error)

    res = client.post(f"/structure/{doc_id}")
    assert res.status_code == status
    assert res.json()["detail"]["blame"] == blame
    assert res.json()["detail"]["message"]


# ── POST /confirm ──────────────────────────────────────────────────────────────


def confirmable(client, monkeypatch) -> tuple[str, dict]:
    doc_id = upload(client)
    script(client, monkeypatch, extracted())
    return doc_id, client.post(f"/structure/{doc_id}").json()


def ids(candidate: dict) -> list[str]:
    led = candidate["ledger"]
    return [
        r["id"]
        for r in (*led["employment"], *led["education"], *led["projects"], *led["credentials"])
    ]


def test_confirming_commits_and_reports_the_new_memory(client, monkeypatch, store):
    doc_id, candidate = confirmable(client, monkeypatch)

    res = client.post(
        "/confirm",
        json={
            "doc_id": doc_id,
            "result": candidate,
            "accept_record_ids": ids(candidate),
            "accept_profile_paths": ["email", "phone_e164"],
            "accept_skills": ["Python", "Go"],
            "confirm_identity": True,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["records_committed"] == 4
    assert body["achievements_committed"] == 3
    assert body["identity_locked"] is True
    assert body["rejections"] == []
    assert body["evidence_chunks"] > 0
    # The response carries the store's own stats, so the client does not have to
    # make a second call to find out what it just changed.
    assert body["memory"]["employment_records"] == 2
    assert store.profile.email == "priya.r@example.com"


def test_confirming_before_structuring_is_404(client, monkeypatch):
    doc_id = upload(client)
    res = client.post("/confirm", json={"doc_id": doc_id, "result": {"doc_id": doc_id}})
    assert res.status_code == 404
    assert "structure it" in res.json()["detail"]


def test_confirming_after_the_document_is_gone_is_refused(client, monkeypatch):
    """The verbatim check needs the source text. Without it every bullet would be
    accepted unverified, which is the one thing this pass exists to prevent — so
    it fails closed rather than committing a document it can no longer read."""
    doc_id, candidate = confirmable(client, monkeypatch)
    client.delete(f"/ingest/documents/{doc_id}")

    res = client.post(
        "/confirm",
        json={"doc_id": doc_id, "result": candidate, "accept_record_ids": ids(candidate)},
    )
    assert res.status_code == 409
    assert "re-upload" in res.json()["detail"]


def test_a_mismatched_doc_id_is_400_not_a_crash(client, monkeypatch):
    doc_id, candidate = confirmable(client, monkeypatch)
    candidate["doc_id"] = "doc_1111111111111111"
    res = client.post("/confirm", json={"doc_id": doc_id, "result": candidate})
    assert res.status_code == 400
    assert "doc_id mismatch" in res.json()["detail"]


def test_the_servers_candidate_wins_over_the_clients(client, monkeypatch, store):
    """The reason the candidate store exists.

    Here the client submits a bullet the model never produced and the document
    never contained, dressed up under an id the model did produce — the shape a
    tampered or buggy review UI would send. If the endpoint compared the request
    against itself it would see "unchanged" and commit it; comparing against the
    server's copy sees an edit, and an edit is the user's own words.

    Either way the invention must not arrive as *parsed* evidence, which is what
    the provenance assertion checks.
    """
    doc_id, candidate = confirmable(client, monkeypatch)
    emp_id = candidate["ledger"]["employment"][0]["id"]

    tampered = {**candidate}
    tampered["ledger"] = {**candidate["ledger"]}
    tampered["ledger"]["employment"] = [
        {
            **candidate["ledger"]["employment"][0],
            "achievements": [
                {
                    **candidate["ledger"]["employment"][0]["achievements"][0],
                    "text": "Personally invented the microservice.",
                }
            ],
        }
    ]

    res = client.post(
        "/confirm",
        json={"doc_id": doc_id, "result": tampered, "accept_record_ids": [emp_id]},
    )
    assert res.status_code == 200
    assert res.json()["achievements_user_authored"] == 1

    committed = store.ledger.employment[0]
    assert committed.provenance.source.value == "user_entered", "not passed off as parsed"


def test_a_rubber_stamped_hallucination_is_refused_over_http(client, monkeypatch, store):
    """The end-to-end version of the premise. The model invents a bullet, the
    client accepts the candidate exactly as it was handed over, and the invention
    still must not reach the evidence index."""
    from app.schemas.structured import CandidateAchievement

    doc = extracted()
    doc.employment[0].achievements.append(
        CandidateAchievement(text="Personally rewrote the Linux kernel over a weekend.")
    )
    doc_id = upload(client)
    script(client, monkeypatch, doc)
    candidate = client.post(f"/structure/{doc_id}").json()
    assert candidate["unverified_quotes"] == 1

    body = client.post(
        "/confirm",
        json={
            "doc_id": doc_id,
            "result": candidate,
            "accept_record_ids": [candidate["ledger"]["employment"][0]["id"]],
        },
    ).json()

    assert len(body["rejections"]) == 1
    assert "unchanged" in body["rejections"][0]["reason"]
    assert body["achievements_committed"] == 2
    assert not any("Linux kernel" in c.text for c in store.evidence.chunks)


def test_your_own_name_is_not_refused_by_a_demo_persons_lock(client, monkeypatch, store):
    """The regression. `get_store()` used to lazily load a demo fixture on first
    read of an empty store, and that fixture's identity arrives already `locked`.

    So confirming your own résumé hit the L0 lock — the guard firing correctly in
    defence of a fictional person — and, silently and worse, your employers were
    appended next to theirs. Memory then held two people, both confirmed, both
    retrievable as evidence for a real cover letter.
    """
    from app.memory.store import STORE, get_store

    STORE.clear()
    assert get_store().is_empty, "the app's own store must not acquire a profile by reading it"

    doc_id, candidate = confirmable(client, monkeypatch)
    body = client.post(
        "/confirm",
        json={
            "doc_id": doc_id,
            "result": candidate,
            "accept_record_ids": ids(candidate),
            "confirm_identity": True,
        },
    ).json()

    assert body["identity_committed"] is True
    assert body["rejections"] == []
    assert store.identity.full_legal_name() == "Priya Raghunathan"
    assert [e.employer for e in store.ledger.employment] == ["Northwind Logistics", "Cobalt Systems"]


def test_the_demo_profile_is_loadable_on_purpose(client, monkeypatch, store):
    """Still wanted — it is the only way to see retrieval work before you have
    confirmed anything. It just has to be something you ask for."""
    assert client.get("/health").json()["memory_empty"] is True

    body = client.post("/memory/demo").json()
    assert body["loaded"] is True
    assert body["memory_empty"] is False
    assert store.identity is not None

    cleared = client.delete("/memory").json()
    assert cleared["memory_empty"] is True
    assert store.identity is None
    assert store.evidence.chunks == [], "the derived layers go too"


def test_nothing_is_committed_by_omission_over_http(client, monkeypatch, store):
    """A request that lists nothing must be a no-op. The wire format defaults every
    accept list to empty, so a client bug that drops a field has to fail safe."""
    doc_id, candidate = confirmable(client, monkeypatch)
    body = client.post("/confirm", json={"doc_id": doc_id, "result": candidate}).json()

    assert body["records_committed"] == 0
    assert store.ledger.employment == []
    assert store.identity is None
