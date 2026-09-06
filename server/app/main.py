"""FastAPI app. Phase 0: one real round trip, plus the trace store the viewer reads."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import get_settings
from .db import close_db, get_db, open_db
from .db import repository as store_db
from .ingest import extract, extract_pasted, get_documents
from .llm import Blame, LLMError, LLMQuotaError, get_client, has_server_key
from .memory.candidates import get_candidates
from .memory.sessions import get_sessions
from .memory.store import get_store
from .pipeline import answer as answer_pipeline
from .pipeline import edit as edit_memory
from .pipeline.confirm import ConfirmRequest, confirm
from .pipeline.structure import structure_document
from .schemas.common import MODE_DESCRIPTION, MODE_MAX_CLAIM_DISTANCE, GenerationMode
from .schemas.trace import AnswerRequest, Trace
from .taxonomy import attestation
from .taxonomy import canonical_questions as cq
from .taxonomy import competencies as comp_tax

#: Bigger than any résumé, small enough that a mis-drag doesn't stall the server.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class SessionCreate(BaseModel):
    jd_text: str | None = None
    mode: GenerationMode = GenerationMode.STRICT
    company: str | None = None
    role_title: str | None = None
    origin: str | None = None


class JdUpdate(BaseModel):
    #: The ceiling is a sanity check, not a limit anyone will meet: a long job
    #: description is about a thousand words.
    jd_text: str = Field(max_length=60000)
    company: str | None = None
    role_title: str | None = None


class PasteRequest(BaseModel):
    text: str
    filename: str | None = None


class SkillWrite(BaseModel):
    """Adding a skill and renaming one take the same body: just the name."""

    name: str = Field(max_length=80)


log = logging.getLogger("jobsync")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    """Open the database, restore memory, and put back any review in progress.

    Loading happens through the module-level `get_store()` rather than the store
    singleton, so a test that swaps it in still exercises this path instead of
    quietly loading into an object nobody reads.
    """
    db = open_db(get_settings().db_path)
    if db is not None:
        found = store_db.load_all(get_store(), get_documents(), get_candidates(), db)
        # Applications in progress come back too. An unfinished Workday form is
        # half an hour of the user's work, and until this line a server restart
        # threw away the job description they had pasted into it.
        restored = store_db.load_sessions(get_sessions(), db)
        log.info(
            "storage: %s (%s, %d session%s in progress)",
            db.path,
            "restored existing memory" if found else "empty",
            restored,
            "" if restored == 1 else "s",
        )
    else:
        log.warning("storage: disabled — nothing you confirm will survive a restart")
    yield
    close_db()


app = FastAPI(
    title="JobSync Intelligence Layer",
    version="0.1.0",
    description="Phase 0 — memory schema, classification, retrieval, and traces.",
    lifespan=lifespan,
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


# ── persistence hooks ──────────────────────────────────────────────────────────
#
# Explicit calls at the few endpoints that change something, rather than a
# write-through store. `MemoryStore` stays a plain object that tests can construct
# and the pipeline can reason about, and the list of things that can write to disk
# is exactly the list of things that can write to memory — visible in one file.


def _persist_memory() -> None:
    if (db := get_db()) is not None:
        store_db.save_memory(get_store(), db)


def _persist_session(session) -> None:  # noqa: ANN001 — ApplicationSession
    """Mirror one session to disk. Called by every endpoint that changes one.

    Per session rather than "save them all": the write happens on the answer path,
    which is the hot one, and rewriting ninety-nine untouched applications to
    record one answer is the kind of cost that turns into a mystery later.
    """
    if (db := get_db()) is not None:
        store_db.save_session(session, db)


@app.get("/health")
def health() -> dict:
    store = get_store()
    db = get_db()
    return {
        "status": "ok",
        "phase": 0,
        "attestation_denylist_version": attestation.VERSION,
        # Whether memory is yours or a demo's is the first thing to know when a
        # confirmation gets refused, so it is reported rather than inferred from
        # the record counts.
        "memory_empty": store.is_empty,
        "memory": store.stats(),
        # Reported, not assumed: "my résumé vanished after a restart" and "storage
        # is off" are the same symptom, and only one of them is a bug.
        "storage": store_db.stats(db) if db is not None else None,
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


@app.get("/meta/llm")
def llm_status(api_key: str | None = None) -> dict:
    """What the LLM layer is configured to do — never the key itself.

    `has_server_key` is the only thing this reports about credentials, and it is a
    boolean by design: a "…last4" preview here would be a key fragment sitting in
    a GET response for no benefit.

    Passing `?api_key=` asks the provider which models that key can actually
    reach, which is worth doing on BYOK: model names get retired, and "404 model
    not found" on a user's first upload is a bad first impression. The call is
    only made when a key is supplied, so the default path stays free and offline.
    """
    s = get_settings()
    out: dict = {
        "provider": "gemini",
        "model_fast": s.llm_model_fast,
        "model_strong": s.llm_model_strong,
        "has_server_key": has_server_key(),
        "require_user_key": s.require_user_key,
        "max_output_tokens": s.llm_max_output_tokens,
        "thinking_budget_fast": s.thinking_budget_fast,
        "models": None,
        "error": None,
    }
    if api_key:
        try:
            out["models"] = get_client(api_key).list_models()
        except LLMError as exc:
            # A 200 with `error` set, not a 4xx: the viewer wants to render "your
            # key was rejected, here's why" next to the rest of the config.
            out["error"] = {"blame": exc.blame.value, "message": exc.user_message()}
    return out


@app.get("/memory")
def memory() -> dict:
    """Everything memory holds, for a page that shows it and lets it be edited.

    `skills` is the merged graph — declared skills plus the ones inferred from the
    achievements that reference them. `declared_skills` is the subset the user
    actually listed, and it is reported separately because it is the only subset
    that can be renamed or removed: an inferred skill exists because a bullet
    points at it, so the honest way to drop one is to edit that bullet. A page
    given only the merged list would offer a delete button that 404s.
    """
    store = get_store()
    return {
        "identity": store.identity.model_dump(mode="json") if store.identity else None,
        "profile": store.profile.model_dump(mode="json") if store.profile else None,
        "ledger": store.ledger.model_dump(mode="json"),
        "skills": [s.model_dump(mode="json") for s in store.graph.skills],
        "declared_skills": [s.model_dump(mode="json") for s in store.declared_skills],
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
        "is_empty": store.is_empty,
    }


@app.post("/memory/demo")
def load_demo() -> dict:
    """Replace memory with the canned demo profile.

    Explicit, and destructive on purpose. This used to happen implicitly on the
    first read of an empty store, which meant a real confirmation landed next to a
    fictional person's records and the L0 lock then refused the real name.
    """
    store = get_store()
    store.load_fixture()
    # Saved, not just loaded in memory. `save_memory` mirrors the store, so the
    # rows belonging to whoever was here before are pruned in the same transaction
    # — otherwise the next restart would reload them alongside the fixture.
    _persist_memory()
    return {"loaded": True, "memory_empty": store.is_empty, "memory": store.stats()}


@app.delete("/memory")
def clear_memory() -> dict:
    """Wipe L0-L2 and the derived layers. The way out of a store holding a mix."""
    store = get_store()
    store.clear()
    if (db := get_db()) is not None:
        # Staged documents and candidates deliberately survive: they are not
        # memory, and the usual reason to clear is to re-confirm the same résumé.
        store_db.wipe_memory(db)
    return {"cleared": True, "memory_empty": store.is_empty, "memory": store.stats()}


# ── editing memory by hand ─────────────────────────────────────────────────────
#
# Until these existed the API could add records and wipe everything, with nothing
# in between: one misread job title meant clearing all of memory and re-uploading
# the résumé. See `pipeline/edit.py` for why an edit appends rather than mutates.


def _edited(payload: dict) -> dict:
    """Save, then answer with the payload plus fresh stats.

    Persisting here rather than in each endpoint keeps "changed memory" and "wrote
    to disk" the same line of code — an edit the user watched succeed and then lost
    to a restart is the worst thing this group of endpoints could do.
    """
    _persist_memory()
    return {**payload, "memory": get_store().stats()}


def _refuse(exc: edit_memory.EditError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@app.patch("/memory/identity")
def patch_identity(body: edit_memory.IdentityPatch, unlock: bool = False) -> dict:
    """Set or correct the legal name. Locked afterwards; changing it needs `unlock`."""
    try:
        identity = edit_memory.edit_identity(body, get_store(), unlock=unlock)
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited({"identity": identity.model_dump(mode="json")})


@app.patch("/memory/profile")
def patch_profile(body: edit_memory.ProfilePatch) -> dict:
    """Contact details, links, work authorization and preferences.

    Authorization and preferences can *only* be set here. A résumé does not state
    them, so `/confirm` refuses them — but they have to be enterable somewhere, and
    by hand is the only honest way in.
    """
    try:
        profile = edit_memory.edit_profile(body, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited({"profile": profile.model_dump(mode="json")})


@app.patch("/memory/records/{record_id}")
def patch_record(record_id: str, body: edit_memory.RecordPatch) -> dict:
    """Correct one ledger record. The old one is kept, flagged, out of retrieval.

    The response carries both ids because the corrected record is a *new* record —
    a client holding the old id needs to know what replaced it rather than
    discovering on its next request that the thing it was editing is inactive.
    """
    try:
        old, new = edit_memory.edit_record(record_id, body, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited(
        {
            "record": new.model_dump(mode="json"),
            "superseded": old.id,
            "evidence_chunks": len(get_store().evidence.chunks),
        }
    )


@app.delete("/memory/records/{record_id}")
def retract_record(record_id: str) -> dict:
    """Take a record out of retrieval. Not a delete — nothing is removed from disk."""
    try:
        record = edit_memory.retract_record(record_id, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited(
        {
            "retracted": record.id,
            "evidence_chunks": len(get_store().evidence.chunks),
        }
    )


@app.post("/memory/skills")
def create_skill(body: SkillWrite) -> dict:
    try:
        skill = edit_memory.add_skill(body.name, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited({"skill": skill.model_dump(mode="json")})


@app.patch("/memory/skills/{skill_id}")
def patch_skill(skill_id: str, body: SkillWrite) -> dict:
    """Fix a typo. `Pyhton` never matches a JD's `Python`, and nothing looks wrong."""
    try:
        skill = edit_memory.rename_skill(skill_id, body.name, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited({"skill": skill.model_dump(mode="json")})


@app.delete("/memory/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict:
    try:
        skill = edit_memory.remove_skill(skill_id, get_store())
    except edit_memory.EditError as exc:
        raise _refuse(exc) from exc
    return _edited({"removed": skill.id})


@app.post("/answer")
def generate_answer(req: AnswerRequest) -> dict:
    store = get_store()
    session = get_sessions().get(req.session_id)
    if req.session_id and session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    trace = answer_pipeline.run(req, store, session)
    # The session recorded this answer and spent the evidence behind it. Both are
    # what stop the next page repeating this one, so they are saved with it.
    if session is not None:
        _persist_session(session)
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


# ── ingest ─────────────────────────────────────────────────────────────────────


def _doc_view(doc) -> dict:  # noqa: ANN001 — RawDocument, plus computed counts
    """Counts are properties on the model, so they must be flattened in by hand."""
    return {
        **doc.model_dump(mode="json"),
        "char_count": doc.char_count,
        "word_count": doc.word_count,
        "line_count": doc.line_count,
        "is_usable": doc.is_usable,
    }


@app.post("/ingest/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Extract text from a résumé. Nothing is written to memory by this call.

    A blocking warning is a 200, not a 4xx: the extraction genuinely happened and
    the client needs the warning text to tell the user what to do about it.
    """
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is {len(data) // 1_048_576} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB.",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    doc = get_documents().put(extract(data, file.filename))
    if (db := get_db()) is not None:
        store_db.save_document(doc, db)
    return _doc_view(doc)


@app.post("/ingest/paste")
def paste_document(body: PasteRequest) -> dict:
    """The escape hatch for scans and exotic templates. Always works."""
    doc = get_documents().put(extract_pasted(body.text, body.filename))
    if (db := get_db()) is not None:
        store_db.save_document(doc, db)
    return _doc_view(doc)


@app.get("/ingest/documents")
def list_documents() -> list[dict]:
    return [_doc_view(d) for d in get_documents().all()]


@app.get("/ingest/documents/{doc_id}")
def get_document(doc_id: str) -> dict:
    doc = get_documents().get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="unknown doc_id")
    return _doc_view(doc)


@app.delete("/ingest/documents/{doc_id}")
def drop_document(doc_id: str) -> dict:
    if (db := get_db()) is not None:
        store_db.delete_document(doc_id, db)
    return {"dropped": get_documents().drop(doc_id)}


# ── step 3: structuring ────────────────────────────────────────────────────────

#: `blame` maps straight onto the status code, because the status is the first
#: thing a client branches on and it should already say who has to act. Sending
#: 502 for a mistyped key would point the user at our status page.
_LLM_STATUS = {
    Blame.USER_KEY: 400,
    Blame.PROVIDER: 502,
    Blame.OURS: 500,
    Blame.CONTENT: 422,
}


def _llm_status(exc: LLMError) -> int:
    # Quota is the exception: it is the user's key, but 429 is what tells a client
    # to back off rather than to re-prompt for credentials.
    if isinstance(exc, LLMQuotaError):
        return 429
    return _LLM_STATUS.get(exc.blame, 500)


def _structure_view(result) -> dict:  # noqa: ANN001 — StructureResult, plus properties
    return {
        **result.model_dump(mode="json"),
        "record_count": result.record_count,
        "achievement_count": result.achievement_count,
        "unverified_quotes": result.unverified_quotes,
        "blocking": [w.model_dump(mode="json") for w in result.blocking()],
    }


@app.post("/structure/{doc_id}")
def structure(doc_id: str, api_key: str | None = None) -> dict:
    """Read a document into candidate records. Still writes nothing to memory.

    The result goes into the candidate store, and the copy kept there is the one
    `/confirm` compares against — which is the whole reason it is stored server-side
    instead of being handed to the client and taken back. Re-posting the same
    doc_id is a deliberate retry and replaces the candidate.
    """
    doc = get_documents().get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="unknown doc_id")
    if not doc.is_usable:
        # 422, not 500: the upload succeeded and the client has a real next step,
        # which is to paste the text instead.
        raise HTTPException(
            status_code=422,
            detail="This document cannot be structured: " + "; ".join(doc.blocking_reasons()),
        )
    try:
        result = structure_document(doc, get_client(api_key))
    except LLMError as exc:
        raise HTTPException(
            status_code=_llm_status(exc),
            detail={"blame": exc.blame.value, "message": exc.user_message()},
        ) from exc
    stored = get_candidates().put(result)
    if (db := get_db()) is not None:
        # This one is worth money. A restart before the user finishes reviewing
        # used to mean paying the model again to read the same document.
        store_db.save_candidate(stored, db)
    return _structure_view(stored)


@app.get("/structure/{doc_id}")
def get_structure(doc_id: str) -> dict:
    result = get_candidates().get(doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail="no candidate for this doc_id; POST first")
    return _structure_view(result)


@app.get("/structure")
def list_structures() -> list[dict]:
    return [_structure_view(r) for r in get_candidates().all()]


@app.delete("/structure/{doc_id}")
def drop_structure(doc_id: str) -> dict:
    """Discarding a review. The document stays; only the reading of it goes."""
    if (db := get_db()) is not None:
        store_db.delete_candidate(doc_id, db)
    return {"dropped": get_candidates().drop(doc_id)}


# ── step 4: confirmation, the only writer to L0/L1/L2 ──────────────────────────


@app.post("/confirm")
def confirm_candidate(req: ConfirmRequest) -> dict:
    """Commit what the user accepted, and refuse what they clicked past.

    Both the candidate and the source text come from the server's own stores rather
    than the request. If the client supplied either, "did the user edit this bullet
    or rubber-stamp the model's invention" would be a question the client answers
    about itself, and the check would be theatre.
    """
    candidate = get_candidates().get(req.doc_id)
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail="no candidate for this doc_id — structure it before confirming",
        )
    doc = get_documents().get(req.doc_id)
    if doc is None:
        # The candidate outlived its document, so the verbatim check has no
        # haystack. Committing anyway would accept every bullet unverified.
        raise HTTPException(
            status_code=409,
            detail="the source document is gone, so bullets cannot be verified; re-upload it",
        )
    try:
        result = confirm(req, candidate, get_store(), doc.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Unconditional, even when everything was rejected: a supersede can fire on a
    # call that commits no new records, and a confirmation the user watched succeed
    # and then lost to a restart is the worst thing this endpoint could do.
    _persist_memory()
    return {
        **result.model_dump(mode="json"),
        "records_committed": result.records_committed,
        "memory": get_store().stats(),
    }


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
    _persist_session(session)
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


@app.post("/sessions/{session_id}/jd")
def set_session_jd(session_id: str, body: JdUpdate) -> dict:
    """Attach the job description to a session that already exists.

    The JD almost always arrives *after* the session does. The extension opens a
    session on the first question it answers, while the description lives on a page
    the user may read later or paste by hand — and on a Workday wizard it is gone
    from the DOM by page 4. Without this endpoint a session opened without a JD
    could never acquire one, and every answer for that application would be written
    for the role in general rather than for this posting.

    Replacing a JD is allowed and reported. Answers already given were written
    against the old one and this call does not revise them, so the count of what is
    now stale is part of the response rather than a surprise later.
    """
    session = get_sessions().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")

    text = body.jd_text.strip()
    if len(text) < 40:
        raise HTTPException(
            status_code=400,
            detail="that is too short to be a job description — paste the posting itself",
        )

    before = session.jd_fingerprint
    session.set_jd(text)
    # Only ever filled in, never blanked: a guess from the page is better than
    # nothing, and a session with no company on it is unidentifiable in a list.
    if body.company:
        session.company = body.company
    if body.role_title:
        session.role_title = body.role_title

    replaced = bool(before and before != session.jd_fingerprint)
    # Before returning, not after: a JD the user pasted by hand is the one piece of
    # session state they cannot reproduce from the page.
    _persist_session(session)
    return {
        **session.model_dump(mode="json"),
        "replaced": replaced,
        "stale_answers": len(session.answered) if replaced else 0,
    }


@app.post("/sessions/{session_id}/next-page")
def next_page(session_id: str, page_url: str | None = None) -> dict:
    """Advance the wizard. Answers and spent evidence carry across the boundary."""
    session = get_sessions().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    session.advance_page(page_url)
    _persist_session(session)
    return session.model_dump(mode="json")


@app.delete("/sessions/{session_id}")
def drop_session(session_id: str) -> dict:
    dropped = get_sessions().drop(session_id)
    # Unconditionally, even when the session was not in memory: a stored row for a
    # session the process has already forgotten would come back on the next restart.
    if (db := get_db()) is not None:
        store_db.delete_session(session_id, db)
    return {"dropped": dropped}


@app.get("/traces")
def list_traces(limit: int = 50) -> list[dict]:
    return [t.model_dump_view() for t in TRACES[:limit]]


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    trace = next((t for t in TRACES if t.trace_id == trace_id), None)
    if trace is None:
        raise HTTPException(status_code=404, detail="unknown trace_id")
    return trace.model_dump_view()
