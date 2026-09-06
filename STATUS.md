# Status

Where the project actually is. Updated 2026-09-07.

Tests: **475 backend** (`server/`), **72 extension** (`extension/`). All passing.
The page (`viewer/`) has no tests of its own — it typechecks and builds, and every
rule it depends on is tested on the backend side.

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

### Hand editing

`pipeline/edit.py` plus seven endpoints. The gap it closed: the API could add
records and wipe all of memory, and nothing in between — so one misread job title
meant clearing everything and re-uploading, which in practice means leaving the
wrong title in and grounding the rest of the application on it.

| Endpoint | What it does |
|---|---|
| `PATCH /memory/records/{id}` | Supersede a job, degree, project or certificate with a corrected copy |
| `DELETE /memory/records/{id}` | Retract it — out of retrieval, still on disk |
| `PATCH /memory/profile` | Contact details, links, work authorisation, preferences |
| `PATCH /memory/identity` | Legal name. Locked, so a change needs `?unlock=true` |
| `POST` / `PATCH` / `DELETE /memory/skills` | Add, fix a typo in, or drop a declared skill |

The decisions worth knowing:

- **Retraction is a third state** (`retracted_at`), not a delete and not a
  supersede — there is no replacement record to point at.
- **A corrected record is inserted directly after the one it replaces**, not
  appended. Insertion order *is* the résumé's order: `load_memory` reloads by it
  and "my last two jobs" reads it, so appending would quietly move a corrected job
  to the bottom of your history.
- **Absent and `null` are different.** `end: null` means "this is my current job";
  absent means "leave it alone". `model_fields_set` is what tells them apart, so no
  patch field may be read with a truthiness check.
- **An unchanged bullet keeps its id, its metrics and its skill links.** Rewriting
  the whole list on every save would break every L3 chunk id, and the page would
  look identical while retrieval quietly changed underneath it.
- **A bullet you typed is `USER_ENTERED`,** so the verbatim guard does not apply.
  The guard exists to catch *model* prose accepted unchanged; a sentence you wrote
  about your own career is the best evidence in the system.
- **Work authorisation and preferences can only arrive here.** `/confirm` refuses
  them on purpose — a résumé does not state them — and typing one *is* its
  confirmation, so the staleness prompt does not fire on a field just filled in.
- **L3/L4 are rebuilt on every edit**, or the page shows the new wording while
  answers cite the old one.

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

One SQLite file (`server/data/jobsync.db`). Layers L0–L2, L5, staged documents
and L6 sessions are stored; L3/L4 are rebuilt. A save makes the database *match* the
store exactly, including deleting rows the store no longer holds — otherwise
loading a different profile leaves the previous person's employment behind, and a
restart resurrects them next to the real ones. There's a test for exactly that.

**Sessions persist too** (migration v2). They are not memory and are never merged
into it, but a session holds the job description you pasted, every answer already
given, and the spent-evidence counter that stops page 6 retelling page 2's story
— half an hour of work that a restart used to delete. `jd_fingerprint` is a real
column because reattaching after navigation looks a session up by it: Workday's
URL changes on every wizard step.

Every restart test uses a fresh store *and* a real file on disk. Reusing the
in-process singletons is how you ship a persistence layer that persists nothing.

### Extension

- MV3, no bundler, no build step. On-demand injection with `allFrames: true`,
  because Greenhouse and Lever render their forms in an iframe.
- **The label cascade** (`src/labels.js`) — seven ordered strategies for working
  out what a field is asking, tested against the real markup Greenhouse, Lever,
  Workday, Ashby and hand-rolled React forms emit. This is the load-bearing part:
  `context_label` is the entire interface to the backend, and a bad label routes a
  real question to ATTESTATION and abstains.
- **The scan follows ARIA roles, not tag names.** Google Forms, Microsoft Forms
  and most React design systems build radios, checkboxes and dropdowns out of
  `<div role="…">` — a scan restricted to `input, textarea, select` returns *zero*
  fields on an eight-question Google Form. Roles are the contract a form has to
  honour for a screen reader, so anything a blind user can fill, the scan finds.
- **Shadow DOM is crossed**, including for id lookups (`getRootNode()`), because
  Workday and Salesforce design systems put their inputs in open shadow roots.
- **Choices are filled by clicking, then read back.** There is no way to "set" a
  div radio, and setting `.checked` on a native one leaves the framework unaware.
  So: click, poll for the state to change, and say so when it never does — never
  claim an answer the page did not accept. Matching is word-level rather than
  substring, because "no" is a substring of "Not applicable".
- Radio groups, checkbox groups (multi-select), native `<select>` and div
  comboboxes, plus a lone checkbox treated as yes/no.
- **The job description is read off the page** (`src/jd.js`): JSON-LD `JobPosting`
  first — the site promised that one to Google — then known platform containers,
  then text density discounting link text. Finding nothing is an explicit outcome
  you can see in the popup, and you can paste the JD by hand instead.
- Scan, per-field fill, highlight-on-click, one session per tab.
- React-safe writes via the prototype `value` setter plus a bubbling `input`
  event — assigning `.value` directly updates the pixels and nothing else.
- Attestation fields get no fill button, and `fill` refuses them a second time at
  the point of the write.

### The profile page

`viewer/` — React + Vite, served on its own at `:5173`, three screens.

- **Add.** Drop a file or paste text, "Read it" structures it and writes nothing,
  then a check-it-over list ticked by default. Bullets the guard could not find
  word-for-word in your document are marked and editable, so the choice is "put it
  in your own words" or "leave it out" rather than a silent drop.
- **Profile.** Everything in memory, editable where you found it: identity (with
  an unlock checkbox that appears only when a legal-name field actually changed),
  contact details, work authorisation, preferences, and each job, degree, project
  and certificate. Superseded and retracted records are filtered out of the view,
  not out of the database.
- **Settings.** What's switched on, where the file is and how many rows are in it,
  why there is no API key box, and a two-step erase.

It talks only to the backend, and so does the extension — no page↔extension
channel, so they cannot disagree. The extension popup has a **Profile** button
which reuses an already-open tab rather than opening a second one, because two
tabs editing the same record means one silently supersedes the other's work.

Two implementation notes that are easy to get wrong:

- **A card saves as a whole, on a button, not per field on blur.** A save
  supersedes the record, so blur-saving would leave one superseded copy behind per
  box you tabbed through.
- **`key={record.id}` on the cards is load-bearing.** A save returns a new id, so
  the card remounts showing what was saved instead of a stale draft.

The debug panels are gone — chunk scores, tag overlap, retrieval traces, session
internals. They were useful while building the pipeline and are noise to anyone
using it. `git log` has them if they are ever wanted back.

---

## Not done

### Placeholders still in the pipeline

| What | Where | Consequence today |
|---|---|---|
| **Real generation** | `pipeline/answer.py:582` `_generate_stub` | Answers are composed from evidence, not written. They're honest and they read like a machine wrote them. This is the biggest single gap. |
| **LLM competency tagger** | `memory/derive.py:164` `_TAG_HINTS` | Tags come from keyword matching. "trained them" produces `['mentorship']` and misses everything else. Must pick from the closed competency list. |
| **Metric detection** | `pipeline/structure.py:544` `_METRIC_RE` | Misses `840ms`, `310ms`, `47 services` — so quantified achievements are treated as unquantified. |

### Gaps in the page

- **No "Other" section.** The catch-all needs a **`Note` record type in L2**. L3
  already has a `NOTE` entity type (`schemas/evidence.py:28`); the L2 side doesn't
  exist, so there is nowhere to put a fact that isn't a job, a degree, a project or
  a certificate.
- **No history view.** Every correction is kept, and there is no screen that shows
  you the chain. The data is all there; the "what did I say last time" question
  currently needs a SQL client.
- **Inferred skills cannot be edited**, correctly — they come from the bullets that
  reference them, so the fix is editing the bullet. `GET /memory` returns
  `declared_skills` separately from the merged graph so the page does not render a
  remove button that 404s, but it does not yet explain *why* the button is missing.
- **No tests.** It typechecks and builds. The rules it relies on are tested on the
  backend, which is where they live, but nothing catches a screen that renders
  blank.
- **Not hosted anywhere.** `npm run dev` on your own machine. A built bundle needs
  the API URL to stop being a dev-server proxy.

### Extension gaps

- **No LLM fallback for labelling.** When the DOM cascade cannot explain a field,
  the field is dropped. The plan is a pruned HTML skeleton sent to a new backend
  endpoint and cached, so the model reads the page the way a person would. Until
  then, a form that labels its questions only visually — by position, colour, or a
  heading it never associates — is invisible to the scan.
- **File uploads are skipped.** A value assignment cannot attach bytes, by design.
- **No per-field edit box**, which means nothing flows back to L5. The
  answer-memory flywheel isn't turning.
- **A JD behind a login is unreachable.** If the posting lives on a page the
  extension never sees, `source` comes back `none` and you paste it by hand. That
  is the honest outcome rather than a bug, but it is still a manual step.
- **Everything DOM-facing is tested in jsdom, which does no layout.** The harness
  fakes `offsetParent` and bounding rects, and simulates the framework that reacts
  to a click. The tests say the logic is right; only a real browser says the page
  agrees. Radio, multi-select and dropdown behaviour on live forms is being
  checked by hand.
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
  is invisibility, not a visible misspelling. `PATCH /memory/skills/{id}` means you
  can now fix one you spot — the id stays put because achievements point at it —
  but spotting it is still on you. Plan: store `name` (what you wrote) alongside
  `canonical` (what it matched) against a closed vocabulary; retrieval uses
  `canonical`; the LLM proposes and you confirm.
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
- **Traces are not stored.** `TRACES` is an in-process list capped at 200, so the
  explanation of why an answer came out the way it did dies with the process. Less
  urgent than it sounds — a trace is a debugging aid, not the user's work — but it
  means yesterday's application cannot be looked at.

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

1. ~~**The three screens, locally.**~~ Done — the page and the edit endpoints
   underneath it. The `Note` record type is the piece left over.
2. **The LLM labelling fallback**, for the forms the DOM cascade cannot explain,
   plus whatever the manual testing of radio and multi-select turns up.
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
