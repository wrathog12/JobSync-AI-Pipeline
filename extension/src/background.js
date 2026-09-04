/* The service worker: the only thing that talks to the backend.
 *
 * Two reasons it goes here rather than in the popup.
 *
 * **The popup dies the instant it loses focus.** A generated answer takes seconds
 * and the user will click away. Work started in a popup is cancelled mid-flight;
 * work started here finishes, and the popup reads the result when it reopens.
 *
 * **`host_permissions` lifts CORS for this context.** A fetch to the backend from
 * a page would be a cross-origin request the server has not allowlisted; from
 * here it is a privileged one, so the server needs no extension-specific CORS
 * entry — which is just as well, since the extension's origin is a generated id.
 *
 * The worker itself is killed aggressively when idle, so nothing important lives
 * in a module variable. Session state goes in `chrome.storage.session`, which is
 * in-memory but survives the worker being torn down and restarted.
 */

const DEFAULTS = {
  backend: 'http://127.0.0.1:8000',
  mode: 'strict',
}

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) }
}

/** Backend call with the error body unwrapped.
 *
 * FastAPI puts everything useful in `detail`, and the LLM errors nest a `blame`
 * and a written explanation inside that. Throwing the status line alone turns
 * "that API key was rejected, paste it again" into "400 Bad Request". */
async function api(path, init) {
  const { backend } = await settings()
  let res
  try {
    res = await fetch(`${backend}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    })
  } catch {
    // Distinguished on purpose: this is the single most common failure and it is
    // not the user's fault or a bug — the server simply is not running.
    throw new Error(`Cannot reach the backend at ${backend}. Is uvicorn running?`)
  }
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json())?.detail
    } catch {
      /* not JSON */
    }
    if (typeof detail === 'string') throw new Error(detail)
    if (detail?.message) {
      throw new Error(detail.blame ? `${detail.message} (${detail.blame})` : detail.message)
    }
    throw new Error(`${res.status} ${res.statusText} on ${path}`)
  }
  return res.json()
}

// ── L6: one application session per tab ───────────────────────────────────────
//
// Per tab, not per extension: a multi-page wizard stays in one tab, and that is
// exactly the span the session is for — prior answers constrain later ones and
// spent evidence is not reused, so page 6 does not retell page 2's story.

const sessionKey = (tabId) => `session:${tabId}`

async function sessionFor(tabId, jdText) {
  const key = sessionKey(tabId)
  const stored = (await chrome.storage.session.get(key))[key]
  if (stored) return stored

  const { mode } = await settings()
  const created = await api('/sessions', {
    method: 'POST',
    body: JSON.stringify({ jd_text: jdText || null, mode }),
  })
  await chrome.storage.session.set({ [key]: created.session_id })
  return created.session_id
}

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(sessionKey(tabId))
})

// ── injection ─────────────────────────────────────────────────────────────────
//
// On demand, rather than a declared content script on every page. A résumé-filling
// tool has no business running on every tab the user opens, and `activeTab` means
// the injection is scoped to a click they made.
//
// `allFrames` matters more than it looks: Greenhouse and Lever are usually
// embedded in an iframe on the employer's own careers page, so the form is almost
// never in the top frame. `executeScript` returns one result per frame, which is
// how a field keeps track of which frame it has to be filled in.

const SCRIPTS = ['src/labels.js', 'src/fields.js']

async function inject(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    files: SCRIPTS,
  })
}

async function scan(tabId) {
  await inject(tabId)
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => window.JobSyncFields.scan(),
  })

  const fields = []
  for (const { frameId, result } of results) {
    if (!result?.fields) continue
    for (const field of result.fields) {
      // Namespaced by frame, because ids are per-frame counters and two frames
      // would otherwise both claim `jf-1`.
      fields.push({ ...field, frameId, key: `${frameId}:${field.id}` })
    }
  }
  const top = results.find((r) => r.frameId === 0)?.result
  return { url: top?.url, title: top?.title, fields }
}

async function fill(tabId, frameId, fieldId, value, fieldClass) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId, frameIds: [frameId] },
    func: (id, text, cls) => window.JobSyncFields.fill(id, text, cls),
    args: [fieldId, value, fieldClass || null],
  })
  return result
}

// ── answering ─────────────────────────────────────────────────────────────────

async function answer(tabId, field, jdText, regenerate) {
  const { mode } = await settings()
  const sessionId = await sessionFor(tabId, jdText)
  const max = field.constraints?.max_value
  const unit = field.constraints?.unit
  return api('/answer', {
    method: 'POST',
    body: JSON.stringify({
      question: field.context_label,
      mode,
      field_type: field.type,
      // Normalised here because `max_chars` is what the request takes. The unit
      // is not thrown away lightly — ~6 characters per word is the same ratio
      // the backend's `Constraints.max_chars` uses, so both ends agree.
      max_chars: max ? (unit === 'words' ? max * 6 : max) : null,
      session_id: sessionId,
      // The session replays an answer it has already given for a field, which is
      // what makes revisiting a page idempotent. "Again" is the user asking for
      // that to be bypassed on purpose.
      regenerate: Boolean(regenerate),
    }),
  })
}

// ── message router ────────────────────────────────────────────────────────────

const HANDLERS = {
  health: () => api('/health'),
  scan: ({ tabId }) => scan(tabId),
  answer: ({ tabId, field, jdText, regenerate }) => answer(tabId, field, jdText, regenerate),
  fill: ({ tabId, frameId, fieldId, value, fieldClass }) =>
    fill(tabId, frameId, fieldId, value, fieldClass),
  highlight: async ({ tabId, frameId, fieldId }) => {
    await inject(tabId)
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId, frameIds: [frameId] },
      func: (id) => window.JobSyncFields.highlight(id),
      args: [fieldId],
    })
    return result
  },
  settings: () => settings(),
  saveSettings: async ({ values }) => {
    await chrome.storage.local.set(values)
    return settings()
  },
  endSession: async ({ tabId }) => {
    const key = sessionKey(tabId)
    const id = (await chrome.storage.session.get(key))[key]
    if (id) {
      await api(`/sessions/${id}`, { method: 'DELETE' }).catch(() => {})
      await chrome.storage.session.remove(key)
    }
    return { ended: Boolean(id) }
  },
}

chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  const handler = HANDLERS[msg?.type]
  if (!handler) {
    respond({ error: `unknown message type: ${msg?.type}` })
    return false
  }
  // Errors are returned as data, never thrown across the boundary: an exception
  // in here reaches the popup as the useless "message port closed before a
  // response was received", which hides whatever actually went wrong.
  handler(msg).then(
    (data) => respond({ data }),
    (err) => respond({ error: String(err?.message || err) })
  )
  return true // keeps the channel open for the async respond
})
