"""FastAPI app. Phase 0: one real round trip, plus the trace store the viewer reads."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .memory.sessions import get_sessions
from .memory.store import get_store
from .pipeline import answer as answer_pipeline
from .schemas.common import MODE_DESCRIPTION, MODE_MAX_CLAIM_DISTANCE, GenerationMode
from .schemas.trace import AnswerRequest, Trace


class SessionCreate(BaseModel):
    jd_text: str | None = None
    mode: GenerationMode = GenerationMode.STRICT
    company: str | None = None
    role_title: str | None = None
    origin: str | None = None
from .taxonomy import attestation
from .taxonomy import canonical_questions as cq
from .taxonomy import competencies as comp_tax

app = FastAPI(
    title="JobSync Intelligence Layer",
    version="0.1.0",
    description="Phase 0 — memory schema, classification, retrieval, and traces.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

#: Phase 0 trace log. Phase 1 persists these to a table — they double as the
#: eval harness, so they are never throwaway.
TRACES: list[Trace] = []
MAX_TRACES = 200


@app.get("/health")
def health() -> dict:
    store = get_store()
    return {
        "status": "ok",
        "phase": 0,
        "attestation_denylist_version": attestation.VERSION,
        "memory": store.stats(),
    }


@app.get("/meta/modes")
def modes() -> list[dict]:
    return [
        {
            "mode": m.value,
            "max_claim_distance": MODE_MAX_CLAIM_DISTANCE[m],
            "description": MODE_DESCRIPTION[m],
        }
        for m in GenerationMode
    ]


@app.get("/meta/competencies")
def competencies() -> list[dict]:
    store = get_store()
    return [
        {
            "tag": c.tag,
            "label": c.label,
            "evidence_count": c.evidence_count,
            "is_answerable": c.is_answerable,
            "is_thin": c.is_thin,
            "is_soft": c.tag in comp_tax.SOFT_COMPETENCIES,
            "strongest_chunk_id": c.strongest_chunk_id,
        }
        for c in store.graph.competencies
    ]


@app.get("/meta/questions")
def questions() -> list[dict]:
    return [
        {
            "id": q.id,
            "label": q.label,
            "field_class": q.field_class.value,
            "profile_path": q.profile_path,
            "competency_tags": list(q.competency_tags),
        }
        for q in cq.all_questions()
    ]


@app.get("/memory")
def memory() -> dict:
    store = get_store()
    return {
        "identity": store.identity.model_dump(mode="json") if store.identity else None,
        "profile": store.profile.model_dump(mode="json") if store.profile else None,
        "ledger": store.ledger.model_dump(mode="json"),
        "skills": [s.model_dump(mode="json") for s in store.graph.skills],
        "evidence": [
            {
                "chunk_id": c.chunk_id,
                "text": c.text,
                "source_label": answer_pipeline._source_label(c),
                "entity_id": c.entity_id,
                "competency_tags": c.competency_tags,
                "metrics": c.metrics,
                "confidence": c.confidence.value,
                "attributed_text": c.attributed_text(),
            }
            for c in store.evidence.chunks
        ],
        "stats": store.stats(),
    }


@app.post("/answer")
def generate_answer(req: AnswerRequest) -> dict:
    store = get_store()
    session = get_sessions().get(req.session_id)
    if req.session_id and session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    trace = answer_pipeline.run(req, store, session)
    TRACES.insert(0, trace)
    del TRACES[MAX_TRACES:]
    return trace.model_dump_view()


@app.post("/answer/compare")
def compare_modes(req: AnswerRequest) -> dict:
    """Run the same question in all three modes side by side.

    This is the fastest way to calibrate the distance thresholds: you see
    exactly what 'aggressive' changed and which claims it stretched.

    Deliberately runs WITHOUT a session even when one is given: three modes
    answering the same field would otherwise spend the same evidence three times
    and poison the session's anti-repetition ledger with two answers the user
    never used.
    """
    store = get_store()
    out = {}
    for mode in GenerationMode:
        trace = answer_pipeline.run(req.model_copy(update={"mode": mode}), store, None)
        TRACES.insert(0, trace)
        out[mode.value] = trace.model_dump_view()
    del TRACES[MAX_TRACES:]
    return out


# ── L6 sessions ────────────────────────────────────────────────────────────────


@app.post("/sessions")
def create_session(body: SessionCreate) -> dict:
    """Open an application. The JD is stored once and reused on every later page."""
    session = get_sessions().create(
        jd_text=body.jd_text,
        mode=body.mode,
        company=body.company,
        role_title=body.role_title,
        origin=body.origin,
    )
    return session.model_dump(mode="json")


@app.get("/sessions")
def list_sessions() -> list[dict]:
    return [s.model_dump(mode="json") for s in get_sessions().all()]


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = get_sessions().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return session.model_dump(mode="json")


@app.post("/sessions/{session_id}/next-page")
def next_page(session_id: str, page_url: str | None = None) -> dict:
    """Advance the wizard. Answers and spent evidence carry across the boundary."""
    session = get_sessions().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    session.advance_page(page_url)
    return session.model_dump(mode="json")


@app.delete("/sessions/{session_id}")
def drop_session(session_id: str) -> dict:
    return {"dropped": get_sessions().drop(session_id)}


@app.get("/traces")
def list_traces(limit: int = 50) -> list[dict]:
    return [t.model_dump_view() for t in TRACES[:limit]]


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    trace = next((t for t in TRACES if t.trace_id == trace_id), None)
    if trace is None:
        raise HTTPException(status_code=404, detail="unknown trace_id")
    return trace.model_dump_view()
