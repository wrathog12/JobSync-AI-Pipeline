/* The popup. Renders what was found, what the backend said about it, and the one
 * button that writes.
 *
 * The rule this UI exists to make visible: **nothing is filled that the user has
 * not looked at.** There is no "fill the form" button, only "answer" — filling is
 * a second, separate click per field, and an ATTESTATION field has no fill button
 * at all. "Answer all" generates; it does not write.
 *
 * That is deliberately slower than a single-click autofill, and it is the product.
 * A wrong answer to "are you legally authorised to work in the US" is not a typo,
 * and an autofill the user did not read is how it gets submitted.
 */

const $ = (id) => document.getElementById(id)

/** Every backend and DOM call goes through the worker, which returns
 * `{data}` or `{error}` rather than throwing across the boundary. */
async function send(type, payload = {}) {
  const res = await chrome.runtime.sendMessage({ type, ...payload })
  if (res?.error) throw new Error(res.error)
  return res?.data
}

const state = {
  tabId: null,
  fields: [],
  /** key -> { trace, error, filled } */
  results: new Map(),
}

const CLASS_NOTE = {
  deterministic: 'read straight from your confirmed memory — no model involved',
  generative: 'written from your evidence',
  attestation: 'you answer this one — it is a statement about you, not about your career',
}

// ── chrome ────────────────────────────────────────────────────────────────────

function banner(message) {
  const el = $('banner')
  el.hidden = !message
  el.textContent = message || ''
}

async function checkHealth() {
  const chip = $('status')
  try {
    const health = await send('health')
    if (health.memory_empty) {
      chip.textContent = 'memory empty'
      chip.dataset.state = 'bad'
      banner(
        'Your memory is empty, so almost everything will abstain. Confirm your résumé in the trace viewer first.'
      )
      return
    }
    const s = health.memory
    chip.textContent = `${s.employment_records} jobs · ${s.evidence_chunks} chunks`
    chip.dataset.state = 'ok'
    if (health.storage === null) {
      banner('Backend storage is off — anything you confirm will vanish on restart.')
    }
  } catch (err) {
    chip.textContent = 'offline'
    chip.dataset.state = 'bad'
    banner(String(err.message))
  }
}

// ── rendering ─────────────────────────────────────────────────────────────────

function limitText(constraints) {
  if (!constraints?.max_value) return null
  return `max ${constraints.max_value} ${constraints.unit} (${constraints.extracted_from})`
}

function render() {
  const list = $('fields')
  list.textContent = ''
  $('empty').hidden = state.fields.length > 0
  $('answerAll').disabled = state.fields.length === 0

  for (const field of state.fields) {
    const result = state.results.get(field.key)
    const trace = result?.trace
    const cls = trace?.field?.field_class

    const li = document.createElement('li')
    li.className = 'field'
    if (cls) li.dataset.class = cls

    const q = document.createElement('div')
    q.className = 'q'
    q.textContent = field.context_label
    q.title = 'Click to find it on the page'
    q.onclick = () =>
      send('highlight', {
        tabId: state.tabId,
        frameId: field.frameId,
        fieldId: field.id,
      }).catch((e) => banner(e.message))
    li.append(q)

    const meta = document.createElement('div')
    meta.className = 'meta'
    for (const text of [
      field.type,
      `via ${field.label_via}`,
      field.constraints?.is_required ? 'required' : null,
      limitText(field.constraints),
      field.frameId ? `frame ${field.frameId}` : null,
      field.current_value ? 'already filled' : null,
    ]) {
      if (!text) continue
      const tag = document.createElement('span')
      tag.className = 'tag'
      tag.textContent = text
      meta.append(tag)
    }
    if (cls) {
      const tag = document.createElement('span')
      tag.className = `tag ${cls}`
      tag.textContent = cls
      tag.title = CLASS_NOTE[cls] || ''
      meta.append(tag)
    }
    li.append(meta)

    if (result?.error) {
      li.append(out(result.error, 'err'))
    } else if (result?.filled) {
      li.append(out(result.filled, 'done'))
    } else if (trace?.abstained) {
      li.append(out(trace.abstain_reason || 'abstained', 'abstain'))
    } else if (trace?.answer) {
      li.append(out(trace.answer))
    }

    li.append(actions(field, trace, cls))
    list.append(li)
  }
}

function out(text, kind) {
  const div = document.createElement('div')
  div.className = kind ? `out ${kind}` : 'out'
  div.textContent = text
  return div
}

function actions(field, trace, cls) {
  const row = document.createElement('div')
  row.className = 'row'

  const answer = document.createElement('button')
  answer.className = 'btn ghost'
  answer.textContent = trace ? 'Again' : 'Answer'
  answer.onclick = () => answerOne(field, { regenerate: Boolean(trace) })
  row.append(answer)

  // No fill button at all for attestation, rather than a disabled one: a greyed
  // button invites hunting for the way to enable it. There isn't one.
  if (trace?.answer && !trace.abstained && cls !== 'attestation') {
    const fill = document.createElement('button')
    fill.className = 'btn'
    fill.textContent = 'Fill'
    fill.onclick = () => fillOne(field, trace)
    row.append(fill)
  }
  return row
}

// ── actions ───────────────────────────────────────────────────────────────────

async function scan() {
  banner('')
  $('scan').disabled = true
  try {
    const found = await send('scan', { tabId: state.tabId })
    state.fields = found.fields
    state.results.clear()
    $('page').textContent = found.title || found.url || ''
    $('endSession').hidden = false
    if (!found.fields.length) {
      banner('No labelled fields found. If the form is behind a "Apply" button, open it first.')
    }
    render()
  } catch (err) {
    banner(err.message)
  } finally {
    $('scan').disabled = false
  }
}

async function answerOne(field, { regenerate } = {}) {
  state.results.set(field.key, { trace: null, error: null })
  render()
  try {
    const trace = await send('answer', { tabId: state.tabId, field, regenerate })
    state.results.set(field.key, { trace })
  } catch (err) {
    state.results.set(field.key, { error: err.message })
  }
  render()
}

async function answerAll() {
  $('answerAll').disabled = true
  try {
    // Sequential, not parallel. The L6 session is what stops page 6 retelling
    // page 2's story, and it only works if each answer can see what the previous
    // one spent — which parallel requests would race past.
    for (const field of state.fields) {
      if (state.results.get(field.key)?.trace) continue
      await answerOne(field)
    }
  } finally {
    $('answerAll').disabled = false
  }
}

async function fillOne(field, trace) {
  try {
    const res = await send('fill', {
      tabId: state.tabId,
      frameId: field.frameId,
      fieldId: field.id,
      value: trace.answer,
      fieldClass: trace.field?.field_class,
    })
    if (res?.ok) {
      const truncated = res.wrote.length < trace.answer.length
      state.results.set(field.key, {
        trace,
        filled: truncated
          ? `Filled, but the page truncated it to ${res.wrote.length} of ${trace.answer.length} characters.`
          : 'Filled. Check it before you submit.',
      })
    } else {
      state.results.set(field.key, { trace, error: res?.reason || 'could not fill' })
    }
  } catch (err) {
    state.results.set(field.key, { trace, error: err.message })
  }
  render()
}

// ── settings ──────────────────────────────────────────────────────────────────

async function loadSettings() {
  const values = await send('settings')
  $('backend').value = values.backend
  $('mode').value = values.mode
}

$('settingsToggle').onclick = () => {
  $('settings').hidden = !$('settings').hidden
}

$('settings').onsubmit = async (event) => {
  event.preventDefault()
  await send('saveSettings', {
    values: { backend: $('backend').value.replace(/\/$/, ''), mode: $('mode').value },
  })
  $('settings').hidden = true
  await checkHealth()
}

$('scan').onclick = scan
$('answerAll').onclick = answerAll
$('endSession').onclick = async () => {
  await send('endSession', { tabId: state.tabId })
  state.results.clear()
  $('endSession').hidden = true
  render()
}

// ── boot ──────────────────────────────────────────────────────────────────────

;(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  state.tabId = tab?.id ?? null
  await loadSettings()
  await checkHealth()
})()
