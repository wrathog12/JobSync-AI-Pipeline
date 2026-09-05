# JobSync

A Chrome extension that fills in job application forms from your own confirmed
history — and refuses to answer the questions it has no business answering.

The point is not speed. Any autofill tool is fast. The point is that every
sentence it writes can be traced back to something you actually did, and that it
declines rather than invents when it can't.

---

## What it does today

1. You upload your CV and project documents once.
2. You review what it extracted and confirm it, item by item. Nothing enters
   memory unconfirmed.
3. On a job application, you click the extension. It reads the form, works out
   what each field is asking, and answers from your memory.
4. **Nothing is written to the page until you click fill on that field.**
   Generating and filling are two separate actions on purpose.

Fields it won't answer at all: sponsorship status, work authorisation, veteran
status, disability, criminal history, and anything else where a wrong answer is a
false statement on a legal document. Those are surfaced to you with no fill
button — not a disabled one, because there is no state in which clicking it would
be correct.

---

## Repository layout

| Path | What it is |
|---|---|
| `server/` | FastAPI backend. The memory, the pipeline, all the rules. |
| `extension/` | The Chrome extension (MV3). Reads forms, writes answers. |
| `viewer/` | A React debug UI. **Developer tool, not the product** — see below. |
| `fixtures/` | Sample profile and form fixtures for tests and demos. |
| `ARCHITECTURE.md` | Why it's built this way. The design review that started it. |
| `STATUS.md` | What is done, what is not, what is next. |

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

### 2. Extension

1. Chrome → `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select the `extension/` folder (the one containing
   `manifest.json`)
4. Pin JobSync to the toolbar

No build step and no bundler — the source is what ships. After editing anything
in `extension/src/`, press ↻ on the extension card, then reload the page you're
testing against.

### 3. Filling your memory

Right now this happens in the viewer, which is a developer tool and looks like
one:

```bash
cd viewer
npm install
npm run dev
```

Upload a document, structure it, then confirm each item. Confirming is what
writes to memory — until you do, the extension will keep saying memory is empty.

**A proper upload/profile page is the next piece of work.** See `STATUS.md`.

---

## Running the tests

```bash
cd server && .venv/Scripts/python.exe -m pytest -q    # 432 tests
cd extension && npm test                              # 31 tests
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

---

## Current limitations

It is single-user by construction: the database schema has `CHECK (id = 1)` on
your identity row. The API key lives in `server/.env` and is yours. The backend
runs on `localhost` and the extension is hard-wired to it.

None of this is an oversight — it's a deliberately scoped first version. The full
list of what's missing, and the order it should be fixed in, is in `STATUS.md`.
Note :- the scraper hasn't been tested through, please fix it for your domain.
