# JobSync — Chrome extension

Reads a job application form, asks the backend what each field is, and fills only
what you approve.

## Loading it

No build step. The files are plain ES modules and load as they are.

1. Start the backend: `cd server && .venv/Scripts/python.exe -m uvicorn app.main:app --reload`
2. `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick this
   `extension/` directory.
3. Open a job application, click the JobSync icon, **Scan this page**.

## The two URLs

⚙ settings holds both, and they are separate because they are different things.

| Setting | Default | What it is |
| --- | --- | --- |
| Backend | `http://127.0.0.1:8000` | The API. Every request goes here. |
| Profile page | `http://127.0.0.1:5173` | The page the **Profile** button opens. The worker never fetches it. |

Both origins are in `host_permissions`. If you move either, change it here *and*
in `manifest.json` — Chrome will not let the worker reach a host the manifest has
not declared, whatever the setting says.

**Profile** reuses an already-open tab rather than opening a second one. Two tabs
editing the same record means one silently supersedes the other's work, and the
person doing it has no way to tell.

## Why there is no build step

A bundler would buy module imports across three files and cost a rebuild between
every edit on a codebase whose interesting problems are all in the DOM. Content
scripts injected as separate files already share one scope, which is the only
thing the imports would have provided. If this grows a framework, add Vite then.

## What is where

| File | Job |
| --- | --- |
| `src/labels.js` | Works out what a field is asking. The cascade that decides whether any of this works. |
| `src/fields.js` | Finds fillable fields, reads limits, writes values React will notice, clicks choices and reads the page back. |
| `src/jd.js` | Finds the job description on the page. JSON-LD first, then platform containers, then text density. |
| `src/background.js` | The only thing that talks to the backend. Owns the L6 session per tab. |
| `src/popup.js` | Renders fields, classifications, answers. Owns the two-click rule and the Profile button. |

## The design rules

**Answering and filling are separate clicks.** "Answer all" generates for every
field and writes nothing. Filling is one click per field, after you have read it.
That is slower than autofill on purpose: a wrong answer to *"are you legally
authorised to work in the US"* is not a typo.

**Attestation fields have no fill button.** Not a disabled one — a greyed button
invites hunting for the way to enable it, and there isn't one. The deny-list is
enforced server-side, but the *write* happens in the page, so `fields.js` refuses
again there. Two independent refusals, because this is the failure that matters.

**Injection is on demand.** No content script is declared, so nothing runs on any
page until you click. `allFrames` is on because Greenhouse and Lever forms are
almost always in an iframe on the employer's careers page.

**Values are written through the prototype's setter.** Assigning `input.value`
directly updates the pixels and not React's state: the next render wipes it and
validation still calls the field empty. `fields.js` uses the native setter and
dispatches a bubbling `input` event, which is what a keystroke produces.

**The scan follows ARIA roles, not tag names.** Google Forms, Microsoft Forms and
most React design systems build radios, checkboxes and dropdowns out of
`<div role="…">`; a scan restricted to `input, textarea, select` returns *zero*
fields on an eight-question Google Form. Roles are the contract a form has to
honour for a screen reader, so anything a blind user can fill, the scan finds.
Shadow roots are crossed for the same reason — Workday and Salesforce put their
inputs inside them.

**A choice is filled by clicking, then read back.** There is no way to "set" a div
radio, and setting `.checked` on a native one leaves the framework unaware. So:
click, poll for the state to change, and say so when it never does — never claim
an answer the page did not accept. Matching is word-level, not substring, because
"no" is a substring of "Not applicable".

## Known gaps

- **File uploads are skipped.** Résumé attachment needs real bytes; a value
  assignment is impossible by design. Wiring this to the stored document is worth
  doing and is not done.
- **No LLM fallback for labelling.** When the cascade cannot explain a field, the
  field is dropped. A form that labels its questions only visually — by position,
  colour, or a heading it never associates — is invisible to the scan.
- **No per-field edit box.** You can fill and then edit in the page, but the
  approval never reaches L5, so the answer-memory flywheel is not turning yet.
- **A JD behind a login is unreachable.** `source` comes back `none` and you paste
  it into the popup by hand. Honest rather than broken, but still a manual step.
- **jsdom does no layout.** The tests fake `offsetParent` and bounding rects and
  simulate the framework that reacts to a click. They say the logic is right; only
  a real browser says the page agrees.
- **No icons** — Chrome shows a grey puzzle piece.
