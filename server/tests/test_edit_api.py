"""Editing memory by hand.

The gap this closes: the API could add records and wipe all of memory, and nothing
in between. One misread job title meant clearing everything and re-uploading the
résumé — so in practice people would leave the wrong title in place, and every
answer for the rest of the application would be grounded in it.

The two tests that matter are the ones about *not* losing things. An edit appends a
corrected record and flags the old one; a removal flags rather than deletes. Both
exist because a record may already have been used in an application that was
submitted, and "what did I tell them last time" has to stay answerable.
"""

from __future__ import annotations

import pytest

from app.memory.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    """The demo profile: two jobs, one degree, two projects, real skills.

    A blank store would make every edit test start by building a résumé, and the
    fixture's identity arrives locked — which is the state the lock tests need.
    """
    s = MemoryStore()
    s.load_fixture()
    return s


@pytest.fixture
def client(monkeypatch, store):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app import main
    from app.config import get_settings

    monkeypatch.setattr(main, "get_store", lambda: store)
    # Storage off, for two reasons. The startup load would otherwise blank the
    # fixture's identity and skills from an empty database — `load_memory` fills a
    # store it assumes is empty — and every edit here would be mirrored into the
    # developer's own `server/data/jobsync.db`, which is not a test's to touch.
    monkeypatch.setattr(
        main, "get_settings", lambda: get_settings().model_copy(update={"db_path": ""})
    )
    with TestClient(app=main.app) as c:
        yield c


def records(store: MemoryStore) -> dict:
    led = store.ledger
    return {r.id: r for r in (*led.employment, *led.education, *led.projects, *led.credentials)}


# ── L2: correcting a record ────────────────────────────────────────────────────


def test_correcting_a_title_keeps_the_old_record(client, store):
    """The heart of it. The old record is not gone — it is flagged and pointed at
    the new one, because an application already sent somewhere used its wording."""
    res = client.patch("/memory/records/emp_01", json={"title": "Staff Engineer"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["superseded"] == "emp_01"
    new_id = body["record"]["id"]
    assert new_id != "emp_01"

    by_id = records(store)
    assert by_id["emp_01"].superseded_by == new_id
    assert by_id["emp_01"].is_active is False
    assert by_id[new_id].title == "Staff Engineer"
    assert by_id[new_id].employer == "Meridian Payments", "untouched fields carry over"
    assert [e.id for e in store.ledger.active_employment()] == [new_id, "emp_02"]


def test_a_corrected_record_is_the_one_retrieval_can_see(client, store):
    """An edit that stopped at L2 would leave the page showing the new wording and
    the answer pipeline citing the old one, which is worse than not editing."""
    before = len(store.evidence.chunks)
    res = client.patch(
        "/memory/records/emp_01",
        json={"achievements": ["Cut checkout latency by 42% by rewriting the settlement path."]},
    )
    new_id = res.json()["record"]["id"]

    texts = [c.text for c in store.evidence.chunks]
    assert any("rewriting the settlement path" in t for t in texts)
    assert not any("moving s" in t for t in texts), "the superseded bullets are not retrievable"
    assert len(store.evidence.chunks) < before
    assert all(not c.entity_id.startswith("emp_01") for c in store.evidence.chunks)
    assert any(c.employer_id == new_id for c in store.evidence.chunks)


def test_a_bullet_the_user_typed_is_their_own_words(client, store):
    """The verbatim guard exists to catch *model* prose accepted unchanged. A
    sentence the user typed about their own career is the best evidence there is,
    and refusing it would mean memory could only hold what a parser read right."""
    res = client.patch(
        "/memory/records/emp_01",
        json={"achievements": ["Rebuilt the reconciliation job and cut its runtime 80%."]},
    )
    new = records(store)[res.json()["record"]["id"]]

    assert new.provenance.source.value == "user_entered"
    assert new.provenance.is_confirmed is True
    assert new.achievements[0].metrics == ["80%"], "figures are re-extracted, not carried over"


def test_an_unchanged_bullet_keeps_its_id_and_its_skill_links(client, store):
    """Rewriting the whole list on every save would break every L3 chunk id and
    every skill link, so the page would look the same and retrieval would not."""
    old = records(store)["emp_01"]
    kept, dropped = old.achievements[0], old.achievements[1]
    assert kept.skill_ids, "the fixture bullet has skill links, or this proves nothing"

    res = client.patch(
        "/memory/records/emp_01", json={"achievements": [kept.text, "A brand new bullet."]}
    )
    new = records(store)[res.json()["record"]["id"]]

    assert new.achievements[0].id == kept.id
    assert new.achievements[0].skill_ids == kept.skill_ids
    assert dropped.text not in [a.text for a in new.achievements]


def test_a_field_the_record_does_not_have_is_an_error(client):
    """Not a silent no-op: a client sending `gpa` to a job has a bug, and swallowing
    it means the user watches their edit disappear with no explanation."""
    res = client.patch("/memory/records/emp_01", json={"gpa": 3.9})
    assert res.status_code == 400
    assert "gpa" in res.json()["detail"]


def test_a_required_field_cannot_be_blanked(client):
    """A job with no employer is not a correction — it is a record nothing can ever
    match, and it would still be sitting in retrieval."""
    res = client.patch("/memory/records/emp_01", json={"employer": "   "})
    assert res.status_code == 400
    assert "employer" in res.json()["detail"]


def test_clearing_an_end_date_means_this_is_my_current_job(client, store):
    """`null` and absent have to differ. `end: None` is what marks a job current,
    and it drives recency ranking — so "leave it alone" cannot be spelled the same
    way as "remove it"."""
    res = client.patch("/memory/records/emp_02", json={"end": None})
    new = records(store)[res.json()["record"]["id"]]
    assert new.dates.end is None
    assert new.dates.is_current is True


def test_editing_a_record_twice_walks_the_chain(client, store):
    """Each edit supersedes the previous one rather than the original, so the
    history reads as a chain and only the last link is active."""
    first = client.patch("/memory/records/emp_01", json={"title": "Wrong"}).json()["record"]["id"]
    second = client.patch(f"/memory/records/{first}", json={"title": "Right"}).json()["record"]["id"]

    by_id = records(store)
    assert by_id["emp_01"].superseded_by == first
    assert by_id[first].superseded_by == second
    assert by_id[second].is_active is True
    assert [e.id for e in store.ledger.employment] == ["emp_01", first, second, "emp_02"], (
        "nothing was deleted, and the chain sits where the original job was"
    )
    assert [e.id for e in store.ledger.active_employment()] == [second, "emp_02"]


def test_editing_a_superseded_record_is_refused(client):
    """Otherwise two edits from two open tabs both succeed and one silently wins."""
    first = client.patch("/memory/records/emp_01", json={"title": "One"}).json()["record"]["id"]
    res = client.patch("/memory/records/emp_01", json={"title": "Two"})
    assert res.status_code == 409
    assert first  # the first edit is the live one
    assert "superseded" in res.json()["detail"]


def test_an_unknown_record_is_a_404(client):
    assert client.patch("/memory/records/emp_nope", json={"title": "x"}).status_code == 404


def test_an_empty_patch_says_so(client):
    res = client.patch("/memory/records/emp_01", json={})
    assert res.status_code == 400
    assert "nothing to change" in res.json()["detail"]


# ── L2: removing a record ──────────────────────────────────────────────────────


def test_removing_a_record_takes_it_out_of_retrieval_but_not_off_disk(client, store):
    """The usual reason to remove: the parser read a job out of a reference or a
    course listing. It leaves retrieval; it stays in the history, because an
    application already submitted may have been built on it."""
    res = client.delete("/memory/records/emp_02")

    assert res.status_code == 200
    assert res.json()["retracted"] == "emp_02"
    record = records(store)["emp_02"]
    assert record.retracted_at is not None
    assert record.is_active is False
    assert record.superseded_by is None, "nothing replaced it — that is the difference"
    assert [e.id for e in store.ledger.active_employment()] == ["emp_01"]
    assert all(c.employer_id != "emp_02" for c in store.evidence.chunks)


def test_removing_the_same_record_twice_is_refused(client):
    assert client.delete("/memory/records/prj_01").status_code == 200
    res = client.delete("/memory/records/prj_01")
    assert res.status_code == 409


def test_a_removed_record_stops_counting_towards_experience(client, store):
    """`total_years_experience` is arithmetic over active jobs and it reaches
    answers directly, so a removal that did not touch it would leave the user
    claiming years from a job they just said was not theirs."""
    before = store.ledger.total_years_experience()
    client.delete("/memory/records/emp_02")
    assert store.ledger.total_years_experience() < before


# ── L1: profile ────────────────────────────────────────────────────────────────


def test_contact_details_can_be_fixed(client, store):
    res = client.patch("/memory/profile", json={"email": "new@example.com"})
    assert res.status_code == 200
    assert store.profile.email == "new@example.com"
    assert store.profile.provenance.source.value == "user_entered"


def test_work_authorization_can_only_be_entered_here(client, store):
    """`/confirm` refuses it on purpose — a résumé does not state it, and inferring
    it from a country of employment is wrong for a large share of visa holders. It
    still has to be enterable, and by hand is the only honest way in."""
    res = client.patch(
        "/memory/profile",
        json={
            "authorization": {
                "country": "IN",
                "status": "citizen",
                "requires_sponsorship": False,
            }
        },
    )

    assert res.status_code == 200
    auth = store.profile.authorization
    assert auth.status.value == "citizen"
    assert auth.requires_sponsorship is False
    assert auth.source.value == "user_entered"
    assert auth.confirmed_at is not None, "typing it *is* the confirmation"
    assert "authorization" not in res.json()["memory"]["stale_paths"], (
        "a field just filled in must not be reported stale"
    )


def test_a_field_the_profile_does_not_have_is_rejected(client):
    """`extra="forbid"`. A typo'd key that returns 200 is how a UI ends up saving
    nothing while showing a success message."""
    res = client.patch("/memory/profile", json={"emial": "new@example.com"})
    assert res.status_code == 422


# ── L0: identity ───────────────────────────────────────────────────────────────


def test_a_locked_name_is_not_overwritten_by_an_edit(client, store):
    res = client.patch("/memory/identity", json={"legal_first": "Someone"})
    assert res.status_code == 409
    assert "unlock" in res.json()["detail"]
    assert store.identity.legal_first == "Aditya"


def test_an_explicit_unlock_changes_the_name(client, store):
    """Names change. The flow for it is deliberate rather than absent."""
    res = client.patch(
        "/memory/identity", params={"unlock": "true"}, json={"legal_last": "Raman-Iyer"}
    )
    assert res.status_code == 200
    assert store.identity.legal_last == "Raman-Iyer"
    assert store.identity.locked is True, "still locked afterwards"


def test_an_identity_can_be_created_by_hand_when_there_is_none():
    """Someone with no résumé to upload still has a name, and until this existed
    the only way to set one was to structure a document."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app import main

    blank = MemoryStore()
    original = main.get_store
    main.get_store = lambda: blank
    try:
        with TestClient(app=main.app) as c:
            res = c.patch("/memory/identity", json={"legal_first": "Priya", "legal_last": "R"})
            assert res.status_code == 200
            assert blank.identity.full_legal_name() == "Priya R"
            assert blank.identity.locked is True

            short = c.patch("/memory/identity", json={"preferred_name": "Pri"})
            assert short.status_code == 409, "created locked, so the next change needs an unlock"
    finally:
        main.get_store = original


# ── L4: declared skills ────────────────────────────────────────────────────────


def test_a_typo_in_a_skill_can_be_corrected(client, store):
    """The quiet failure this fixes: retrieval is keyword-based, so `Pyhton` stops
    matching a JD's `Python` and the symptom is invisibility, not a misspelling."""
    res = client.patch("/memory/skills/sk_python", json={"name": "Python 3"})
    assert res.status_code == 200
    assert [s.name for s in store.declared_skills if s.id == "sk_python"] == ["Python 3"]


def test_renaming_keeps_the_id_because_achievements_point_at_it(client, store):
    linked = [a for job in store.ledger.employment for a in job.achievements if a.skill_ids]
    assert linked, "the fixture links bullets to skills, or this proves nothing"
    target = linked[0].skill_ids[0]

    client.patch(f"/memory/skills/{target}", json={"name": "Renamed"})

    assert any(s.id == target for s in store.declared_skills)
    assert linked[0].skill_ids[0] == target


def test_a_skill_can_be_added_and_removed(client, store):
    res = client.post("/memory/skills", json={"name": "Elixir"})
    assert res.status_code == 200, res.text
    added = res.json()["skill"]
    assert added["id"] == "sk_elixir"
    assert any(s.name == "Elixir" for s in store.declared_skills)

    assert client.delete(f"/memory/skills/{added['id']}").status_code == 200
    assert not any(s.name == "Elixir" for s in store.declared_skills)


def test_the_same_skill_is_not_listed_twice(client):
    assert client.post("/memory/skills", json={"name": "python"}).status_code == 409


def test_a_soft_skill_is_still_refused(client):
    """Same refusal as `/confirm`, for the same reason: everyone would list
    "communication", it is unfalsifiable, and the graph already reports it from the
    achievements that demonstrate it."""
    res = client.post("/memory/skills", json={"name": "communication"})
    assert res.status_code == 400
    assert "soft skill" in res.json()["detail"]


def test_an_unknown_skill_is_a_404(client):
    assert client.delete("/memory/skills/sk_nope").status_code == 404
