"""Attaching a job description to a session that already exists.

The JD arrives after the session almost every time: the extension opens a session
on the first question it answers, while the description lives on a page the user
reads earlier or pastes later, and on a Workday wizard it is out of the DOM by
page 4. Before this endpoint existed a session opened without a JD could never
acquire one, so `answer.py` — which has mixed the JD into the retrieval query all
along — was reading a field that nothing ever filled.

The replacement test is the one that matters. Swapping the JD mid-application does
not revise the answers already given, and a caller that cannot tell it happened
will keep believing every answer was written against the description now on file.
"""

from __future__ import annotations

import pytest

JD = (
    "Staff Backend Engineer. You will own the ingestion pipeline end to end, "
    "from parsing uploaded documents through to the retrieval layer. Required: "
    "five years of Python, production experience with retrieval systems."
)

OTHER_JD = (
    "Frontend Engineer, Design Systems. You will own the component library and "
    "the accessibility work across every product surface. Required: TypeScript, "
    "React, and a real interest in how screen readers behave."
)


@pytest.fixture
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app import main
    from app.memory.sessions import get_sessions

    with TestClient(app=main.app) as c:
        yield c
    get_sessions()._sessions.clear()  # noqa: SLF001 — a store with no public reset


def open_session(client, **kw) -> str:
    res = client.post("/sessions", json={"mode": "strict", **kw})
    assert res.status_code == 200
    return res.json()["session_id"]


def test_a_session_opened_without_a_jd_can_be_given_one(client):
    session_id = open_session(client)
    assert client.get(f"/sessions/{session_id}").json()["jd_text"] is None

    res = client.post(f"/sessions/{session_id}/jd", json={"jd_text": JD})

    assert res.status_code == 200
    body = res.json()
    assert body["jd_text"] == JD
    assert body["jd_fingerprint"]
    assert body["replaced"] is False
    # Read back through a different endpoint: the point is that it stuck, not that
    # the response echoed it.
    assert client.get(f"/sessions/{session_id}").json()["jd_text"] == JD


def test_the_role_and_company_label_the_session(client):
    session_id = open_session(client)
    client.post(
        f"/sessions/{session_id}/jd",
        json={"jd_text": JD, "company": "Northwind Labs", "role_title": "Staff Engineer"},
    )
    session = client.get(f"/sessions/{session_id}").json()
    assert session["company"] == "Northwind Labs"
    assert session["role_title"] == "Staff Engineer"


def test_a_guess_is_never_blanked_by_a_later_call(client):
    """The extension guesses the company from the hostname and may later post a
    JD with nothing better. Overwriting the guess with `None` would leave the
    session unidentifiable in a list for no gain."""
    session_id = open_session(client, company="Northwind Labs")
    client.post(f"/sessions/{session_id}/jd", json={"jd_text": JD})
    assert client.get(f"/sessions/{session_id}").json()["company"] == "Northwind Labs"


def test_replacing_the_jd_says_how_many_answers_are_now_stale(client):
    """Answers already given were written against the old description and this
    call does not revise them. A silent replacement means the caller believes the
    whole application was tailored to a posting most of it never saw."""
    from app.memory.sessions import get_sessions
    from app.schemas.session import AnsweredField, field_key

    session_id = open_session(client)
    client.post(f"/sessions/{session_id}/jd", json={"jd_text": JD})
    get_sessions().get(session_id).record(
        AnsweredField(
            field_key=field_key("Why this role?"),
            question="Why this role?",
            answer="Because I have owned an ingestion pipeline before.",
            mode="strict",
            trace_id="tr_test",
        )
    )

    body = client.post(f"/sessions/{session_id}/jd", json={"jd_text": OTHER_JD}).json()

    assert body["replaced"] is True
    assert body["stale_answers"] == 1


def test_re_posting_the_same_jd_is_not_a_replacement(client):
    """The extension re-reads the page on every popup open. Reporting that as a
    replacement would cry wolf on the one signal that matters."""
    session_id = open_session(client, jd_text=JD)
    body = client.post(f"/sessions/{session_id}/jd", json={"jd_text": f"  {JD}  "}).json()
    assert body["replaced"] is False


def test_a_stray_line_of_text_is_refused(client):
    """A JD that is really the page's cookie banner is worse than no JD: it steers
    every answer in the application and nothing on screen looks wrong."""
    session_id = open_session(client)
    res = client.post(f"/sessions/{session_id}/jd", json={"jd_text": "Apply now"})
    assert res.status_code == 400
    assert "job description" in res.json()["detail"]
    assert client.get(f"/sessions/{session_id}").json()["jd_text"] is None


def test_an_unknown_session_is_a_404_not_a_new_session(client):
    res = client.post("/sessions/sess_nope/jd", json={"jd_text": JD})
    assert res.status_code == 404
