# JobSync — Chrome extension

Reads a job application form, asks the backend what each field is, and fills only
what you approve.

## Loading it

No build step. The files are plain ES modules and load as they are.

1. Start the backend: `cd server && .venv/Scripts/python.exe -m uvicorn app.main:app --reload`
2. `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick this
   `extension/` directory.
3. Open a job application, click the JobSync icon, **Scan this page**.

If the backend is on a different port, change it in the popup's ⚙ settings and
add that origin to `host_permissions` in `manifest.json` — Chrome will not let the
worker reach a host the manifest has not declared, whatever the setting says.

## Why there is no build step

A bundler would buy module imports across three files and cost a rebuild between
every edit on a codebase whose interesting problems are all in the DOM. Content
scripts injected as separate files already share one scope, which is the only
thing the imports would have provided. If this grows a framework, add Vite then.

## What is where

| File | Job |
| --- | --- |
| `src/labels.js` | Works out what a field is asking. The cascade that decides whether any of this works. |
| `src/fields.js` | Finds fillable fields, reads limits, writes values React will notice. |
| `src/background.js` | The only thing that talks to the backend. Owns the L6 session per tab. |
| `src/popup.js` | Renders fields, classifications, answers. Owns the two-click rule. |

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

## Known gaps

- **Checkboxes and radios are not filled.** Nearly all of them are consents or
  attestations, and the rest are one click.
- **File uploads are skipped.** Résumé attachment needs real bytes; a value
  assignment is impossible by design. Wiring this to the stored document is worth
  doing and is not done.
- **No JD capture yet.** The session is created without one, so nothing is
  tailored to the posting. Reading the JD off the page is the obvious next step.
- **No per-field edit box.** You can fill and then edit in the page, but the
  approval never reaches L5, so the answer-memory flywheel is not turning yet.
- **Workday's shadow DOM.** `querySelectorAll` does not cross shadow roots, so
  some Workday tenants will scan as empty.
