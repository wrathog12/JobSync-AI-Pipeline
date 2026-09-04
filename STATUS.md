# Status

Where the project actually is. Updated 2026-09-04.

Tests: **432 backend** (`server/`), **31 extension** (`extension/`). All passing.

The rule for this file: a thing is *done* only if it works end to end and has a
test that would fail if it broke. Everything else is in "Not done", even if code
for it exists.

---

## Done

### The memory — all six layers exist and are typed

| Layer | What it holds | Where |
|---|---|---|
| L0 | Identity — legal name, locked once set | `schemas/identity.py` |
| L1 | Profile — contact details, links, one provenance for the lot | `schemas/profile.py` |
| L2 | Ledger — employment, education, projects, credentials. Append-only in the domain: records are superseded, never edited in place | `schemas/ledger.py` |
| L3 | Evidence index — retrievable chunks, each with a hard pointer back to the L2 record it came from | `schemas/evidence.py` |
| L4 | Competency graph and declared skills | `schemas/competency.py` |
| L5 | Answer memory — answers you approved, reusable per company | `schemas/answer_memory.py` |
| L6 | Application session — one multi-page form in progress, tracking which evidence has been spent | `schemas/session.py` |

L3 and L4 are **derived** and never stored — they are rebuilt from L0–L2 on every
commit and on every restart. That is deliberate: a stale derived layer is a bug
you cannot see, and rebuilding is milliseconds.

### Ingest

- PDF via **PyMuPDF**, at line granularity, with two-column detection
  (`ingest/columns.py`) — résumés are frequently two-column and naive extraction
  interleaves the columns into nonsense.
- DOCX via `python-docx`. Plain paste as a third path.
- Quality gates: too little text, too much garbage, wrong file type — all
  rejected with a reason rather than half-ingested.

### LLM seam

- Gemini client, schema-first calls (the model is asked for JSON matching a
  Pydantic model, not for prose that gets parsed).
- `FakeClient` for tests, so the whole pipeline runs with zero tokens.
- Failures are **attributed** — a `blame` field distinguishes "the model returned
  garbage" from "the network died" from "you're out of quota". Without this, every
  failure looks the same and none are debuggable.
- Responses cached by content hash, so re-running a document is free.

### Structuring and confirmation

- `POST /structure/{doc_id}` — LLM turns a document into a *candidate*: proposed
  employment, education, projects, skills.
- `POST /confirm` — you approve it, item by item, and only then does it enter
  memory. Supersedes rather than overwrites.
- **The verbatim guard.** An achievement bullet must appear word-for-word in the
  source document, or be marked `USER_ENTERED` because you typed it. Anything else
  is refused. This is the single rule that keeps the generator from inventing a
  job you never had.

### Classification

A four-tier cascade in `pipeline/classify.py`, cheapest first:

1. **Attestation deny-list** — free, checked first, always. Sponsorship, work
   authorisation, veteran status, disability, criminal history.
2. **Alias dictionary** — free, matches known question phrasings above
   `ALIAS_FLOOR = 0.55`.
3. **LLM classifier** — cached by `hash(domain + label + type)`.
4. **Below the floor → ATTESTATION**, never GENERATIVE. When unsure, abstain.

### Answering

- Deterministic lookups (email, phone, name, links) are a keyed read — **zero
  tokens**. Roughly 80% of real form fields are these, and semantic search over
  them is strictly worse than a dictionary.
- Prose questions go tags → retrieval → generator.
- Retrieval is **BM25 keyword**, hand-rolled in `retrieval/lexical.py`.
- Grounding check (`pipeline/ground_check.py`) verifies the output actually used
  the evidence rather than merely being handed it.
- Three modes — strict / optimize / aggressive — with the "distance" from
  evidence recorded per answer, so you can see how far a mode strays.
- Session-aware: evidence already spent on an earlier question is penalised, so a
  five-question form doesn't answer the same thing five times.
- Full trace per answer: what was retrieved, what scored what, why it abstained.

### Persistence

One SQLite file (`server/data/jobsync.db`). Layers L0–L2, L5 and staged
documents are stored; L3/L4 are rebuilt. A save makes the database *match* the
store exactly, including deleting rows the store no longer holds — otherwise
loading a different profile leaves the previous person's employment behind, and a
restart resurrects them next to the real ones. There's a test for exactly that.

### Extension

- MV3, no bundler, no build step. On-demand injection with `allFrames: true`,
  because Greenhouse and Lever render their forms in an iframe.
- **The label cascade** (`src/labels.js`) — seven ordered strategies for working
  out what a field is asking, tested against the real markup Greenhouse, Lever,
  Workday, Ashby and hand-rolled React forms emit. This is the load-bearing part:
  `context_label` is the entire interface to the backend, and a bad label routes a
  real question to ATTESTATION and abstains.
- Scan, per-field fill, highlight-on-click, one session per tab.
- React-safe writes via the prototype `value` setter plus a bubbling `input`
  event — assigning `.value` directly updates the pixels and nothing else.
- Attestation fields get no fill button.

### Viewer

A React debug UI covering ingest, review, memory, sessions and traces. **This is
a developer tool.** It exposes chunk scores, tag overlap and retrieval internals
because that's what's useful while building. It is not the shipping UI.

---

## Not done

### Placeholders still in the pipeline

| What | Where | Consequence today |
|---|---|---|
| **Real generation** | `pipeline/answer.py:582` `_generate_stub` | Answers are composed from evidence, not written. They're honest and they read like a machine wrote them. This is the biggest single gap. |
| **LLM competency tagger** | `memory/derive.py:164` `_TAG_HINTS` | Tags come from keyword matching. "trained them" produces `['mentorship']` and misses everything else. Must pick from the closed competency list. |
| **Metric detection** | `pipeline/structure.py:544` `_METRIC_RE` | Misses `840ms`, `310ms`, `47 services` — so quantified achievements are treated as unquantified. |

### The product UI — decided, not built

The plan settled on: an **independently hosted page**, separate from the
extension, talking to the same backend. Three screens and nothing else:

1. **Upload** — drop CV and project docs.
2. **Profile** — Experience / Projects / Education / Links / Other, every item
   editable inline.
3. **Settings** — API key, name and email, backend URL.

Cut from what the viewer shows: chunk counts, retrieval scores, tag lists,
evidence panels, `/health` internals, "answered from 3 sources". Nobody outside
this repo cares.

Not bundled inside the extension, and **not** wired directly to the extension
either: page → backend, extension → backend, and they agree because the backend is
the only source of truth. A direct page↔extension channel buys nothing and adds a
second thing to debug.

The catch-all "Other" section needs a **`Note` record type in L2**. L3 already
has a `NOTE` entity type (`schemas/evidence.py:28`); the L2 side doesn't exist.

### Extension gaps

- **Radio groups are scanned but never filled** — refused on purpose, since a
  radio is usually a consent or an attestation. Whether that's the right call for
  ordinary multiple-choice questions is untested.
- **Multi-select isn't found at all.** Most ATS "multi-selects" aren't
  `<select multiple>` — they're a React combobox built from divs with a hidden
  input. The scan looks for `input, textarea, select` and sees nothing.
- **File uploads are skipped.** A value assignment cannot attach bytes, by design.
- **No JD capture** — sessions are created with `jd_text: null`, so answers aren't
  tailored to the specific posting.
- **No per-field edit box**, which means nothing flows back to L5. The
  answer-memory flywheel isn't turning.
- **Workday's shadow DOM** is out of reach of the current scan.
- **Visibility checking is untested in a real browser.** jsdom does no layout, so
  the test harness fakes `offsetParent` and bounding rects. The tests can't tell
  you whether `isVisible` behaves on a real page.
- **No icons** — Chrome shows a grey puzzle piece.

### Retrieval and quality

- **No eval set.** `RELEVANCE_FLOOR = 0.45`, `MIN_CHUNKS = 2` and the spent-chunk
  penalty are guesses. Calibrating them needs a labelled set *including
  negatives* — questions the memory genuinely cannot answer, where abstaining is
  the correct output.
- **BM25 is hand-rolled Python.** SQLite FTS5 would replace it; the schema is
  already shaped for it. Not urgent at a few thousand chunks.
- **No skill canonicalisation.** A typo'd skill (`Pyhton`) is stored as typed, and
  BM25 is keyword-based, so it silently stops matching a JD's `Python`. The damage
  is invisibility, not a visible misspelling. Plan: store `name` (what you wrote)
  alongside `canonical` (what it matched) against a closed vocabulary; retrieval
  uses `canonical`; the LLM proposes and you confirm.
- **Skills are toggle-only in review** (`viewer/src/ReviewPanel.tsx`) — a typo can
  be dropped but not corrected.
- **No multi-document dedup.** Loading twenty project files will produce twenty
  overlapping sets of records. L2 project records should also track "on résumé"
  vs "not".

### Missing features

- **`POST /answer/refine`** — refine an answer instead of regenerating it, and
  feed the result to L5.
- **Attestation-with-help** — you supply the fact in a few words, the LLM writes
  the sentence, the fact persists to L1. Currently attestations are entirely
  manual, every time.
- **Résumé and cover-letter generation.** The actual output artifact of the whole
  project, and it doesn't exist yet.

### Going public

Not blockers for your own use; all of them blockers for anyone else's.

- **Single-user by construction.** The schema has `CHECK (id = 1)` on identity —
  one person, forever. Multi-user means accounts, per-user rows, auth on every
  endpoint, and Postgres instead of a SQLite file. `MemoryStore` was written so
  this touches one file, but it's still the largest remaining piece of work.
- **BYOK.** The key is in `server/.env` and it's yours; anyone installing this
  would spend your quota. Note that hashing is the wrong tool — the key must be
  *decryptable* to be sent to Google, so it's encryption at rest, not hashing.
  And on a single-user local machine, encryption at rest is not meaningfully safer
  than `.env`: whatever can run the app can decrypt the key. It starts mattering
  the moment the key crosses a network to a server you host.
- **The backend URL is hard-coded** to `127.0.0.1:8000` in
  `extension/manifest.json`.
- **Store listing** needs icons (16/48/128), screenshots, and a privacy policy —
  the extension reads form fields, so that's not optional.

---

## Order of work

1. **The three screens, locally.** Still single-user, still your machine. Get the
   upload/edit loop pleasant before adding anything underneath it.
2. **Radio and multi-select handling**, with manual testing against real forms.
3. **Real generation** — replace `_generate_stub`. Everything downstream of it is
   already built and waiting.
4. **LLM competency tagger** and skill canonicalisation, together — they're the
   same ingest pass.
5. **Eval set with negatives**, then tune the floors against it rather than by
   feel.
6. **Résumé and cover-letter generation.**
7. **Multi-user, auth, Postgres, BYOK** — only when other people are actually
   going to use it.

Doing 7 alongside 1 means debugging a UI and an auth system simultaneously. Don't.
