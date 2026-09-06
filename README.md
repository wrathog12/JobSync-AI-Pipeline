# JobSync

A Chrome extension that fills in job application forms from your own confirmed
history — and refuses to answer the questions it has no business answering.

The point is not speed. Any autofill tool is fast. The point is that every
sentence it writes can be traced back to something you actually did, and that it
declines rather than invents when it can't.

---

## What it does today

1. You upload your CV and project documents once, on the profile page.
2. You review what it extracted and confirm it, item by item. Nothing enters
   memory unconfirmed.
3. Anything it read wrong you fix by hand, on the same page, at any time.
4. On a job application, you click the extension. It reads the job description
   off the page, reads the form, works out what each field is asking, and answers
   from your memory.
5. **Nothing is written to the page until you click fill on that field.**
   Generating and filling are two separate actions on purpose.

It finds the questions by their ARIA roles rather than their tags, so a form built
entirely out of `<div>`s — Google Forms, Microsoft Forms, most React design
systems — is read the same as one built out of `<input>`s. Text boxes, radio
groups, checkbox groups, dropdowns. A choice is filled by clicking it and then
reading the page back: if the page does not confirm the click, it tells you so
instead of claiming the answer went in.

If the description isn't on the page — behind a login, or on a wizard step you
already passed — the popup says so and you can paste it in. Answers are written
against the posting, so this is worth doing.

Fields it won't answer at all: sponsorship status, work authorisation, veteran
status, disability, criminal history, and anything else where a wrong answer is a
false statement on a legal document. Those are surfaced to you with no fill
button — not a disabled one, because there is no state in which clicking it would
be correct.

---

## The profile page

A separate page — not part of the extension — with three screens:

- **Add** — drop a CV or a project document, read it, tick the items that are
  right, fix the ones that aren't, save. Bullets it could not find word-for-word
  in your document are flagged, and you either edit them into your own words or
  leave them out.
- **Profile** — everything in memory, every item editable where you found it. Your
  name, contact details, work authorisation, what you're looking for, and each
  job, degree, project and certificate.
- **Settings** — what's switched on, where the file lives, and the two buttons
  that throw it all away.

Editing never overwrites. A correction saves a new version and keeps the old one,
flagged and out of use — because if you already sent an application built on the
old wording, that record is the only thing left that can tell you what you said.
Removing something works the same way: out of use, still on disk.

It runs beside the backend rather than inside the extension, and the two never
talk to each other directly: page → backend, extension → backend. The backend is
the only source of truth, so they cannot disagree.

---

## Repository layout

| Path | What it is |
|---|---|
| `server/` | FastAPI backend. The memory, the pipeline, all the rules. |
| `extension/` | The Chrome extension (MV3). Reads forms, writes answers. |
| `viewer/` | The profile page (React + Vite). Upload, edit, settings. |
| `fixtures/` | Sample profile and form fixtures for tests and demos. |
| `ARCHITECTURE.md` | Why it's built this way. The design review that started it. |
| `STATUS.md` | What is done, what is not, what is next. |

`viewer/` keeps its old directory name because renaming it would rewrite every
import and every path in this file for no gain. The package inside it is
`jobsync-page`.

---

## Running it

You need Python 3.11+, Node 18+, and Chrome 116+.

### 1. Backend

```bash
cd server
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"    # Windows
# source .venv/bin/activate && pip install -e ".[dev]" # macOS / Linux
```

Copy `.env.example` to `.env` and put your Gemini API key in it:

```
GEMINI_API_KEY=...
```

Then start it **from the `server/` directory** — the SQLite file is created
relative to where you launch it, so starting elsewhere silently gives you a
second, empty memory:

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Check `http://127.0.0.1:8000/health`. The `storage` block tells you where your
memory lives and how many rows are in it.

### 2. Profile page

```bash
cd viewer
npm install
npm run dev
```

It opens on `http://127.0.0.1:5173` and proxies `/api` to the backend on port
8000. If you started the backend somewhere else, `API_PORT=8011 npm run dev`.

Upload a document, tick what's right, save. Saving is what writes to memory —
until you do, the extension will keep saying memory is empty.

### 3. Extension

1. Chrome → `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select the `extension/` folder (the one containing
   `manifest.json`)
4. Pin JobSync to the toolbar

No build step and no bundler — the source is what ships. After editing anything
in `extension/src/`, press ↻ on the extension card, then reload the page you're
testing against.

The popup's **Profile** button opens the page above, reusing the tab if it is
already open. Both URLs are in the popup's ⚙ settings, and both origins are in
`host_permissions` — Chrome blocks any host the manifest has not declared,
whatever the setting says.

---

## Running the tests

```bash
cd server && .venv/Scripts/python.exe -m pytest -q    # 475 tests
cd extension && npm test                              # 72 tests
cd viewer && npx tsc --noEmit                         # the page typechecks
```

---

## The three rules

These are the load-bearing decisions. Everything else is negotiable.

**1. Confirmation is not a formality.** An LLM extracts structure from your
documents; you approve it. The approved copy is the only thing the answer
pipeline can see. An unconfirmed extraction is a suggestion, not a fact.

**2. A résumé bullet must be verbatim from a document you uploaded, or typed by
you.** `confirm.py` refuses anything else. This is the only reason the generator
cannot invent a job you never had. It costs a little convenience — you can't
have an LLM tidy up your phrasing at ingest, because then every bullet is
non-verbatim and the guard fails open.

**3. Attestations are never generated.** Checked first, before any LLM is
consulted, against a deny-list — and refused again in the page, because that's
where the write actually happens and it's the last place that can say no.

**4. Nothing in your history is ever deleted or overwritten.** An edit appends a
corrected version and flags the old one. A removal flags it and leaves it. This
costs a row per correction and buys the one question a submitted application makes
you ask: what did I tell them last time.

---

## Current limitations

It is single-user by construction: the database schema has `CHECK (id = 1)` on
your identity row. The API key lives in `server/.env` and is yours. Both the
backend and the page run on `localhost`, and the two origins the extension may
reach are fixed in `manifest.json`.

None of this is an oversight — it's a deliberately scoped first version. The full
list of what's missing, and the order it should be fixed in, is in `STATUS.md`.
