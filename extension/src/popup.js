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
  /** The description this application is being written against, or null. */
  jd: null,
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

// ── the job description ───────────────────────────────────────────────────────

const SOURCE_NAME = {
  'json-ld': "the page's own job posting data",
  container: 'the description on the page',
  density: 'the main text of the page',
  pasted: 'what you pasted',
}

function showJd(jd) {
  state.jd = jd || null
  const summary = $('jdSummary')
  if (!jd?.jd_text) {
    summary.textContent =
      'No job description attached — answers will be written for the role in general.'
    return
  }
  const words = jd.jd_text.split(/\s+/).filter(Boolean).length
  const who = [jd.role_title, jd.company].filter(Boolean).join(' · ')
  const from = SOURCE_NAME[jd.source] || jd.source
  summary.textContent = `${who || 'Job description'} — ${words} words, from ${from}.`
}

async function loadJd() {
  try {
    showJd(await send('jd', { tabId: state.tabId }))
  } catch {
    showJd(null) // the worker knowing nothing is not worth a banner
  }
}

/** Read it, attach it, and say where it came from.
 *
 * Attaching without a confirmation step is deliberate, and is not the same call as
 * filling a field: this is input, not output — nothing is written to the form and
 * a bad grab is fixed by editing it. What is *not* acceptable is a silent one, so
 * the source and the length are always on screen. */
async function readJd() {
  banner('')
  $('readJd').disabled = true
  try {
    const found = await send('readJd', { tabId: state.tabId })
    if (!found?.jd_text) {
      banner('Could not find a job description on this page — paste it instead.')
      $('jdForm').hidden = false
      $('jdText').focus()
      return
    }
    showJd(await send('useJd', { tabId: state.tabId, jd: found }))
    $('jdText').value = found.jd_text
    if (found.truncated) banner('The description was long, so only the first part was kept.')
  } catch (err) {
    banner(err.message)
  } finally {
    $('readJd').disabled = false
  }
}

$('readJd').onclick = readJd

$('jdToggle').onclick = () => {
  const form = $('jdForm')
  form.hidden = !form.hidden
  if (!form.hidden) {
    $('jdText').value = state.jd?.jd_text || $('jdText').value
    $('jdText').focus()
  }
}

$('jdForm').onsubmit = async (event) => {
  event.preventDefault()
  banner('')
  try {
    const jd = { jd_text: $('jdText').value, source: 'pasted', url: null }
    showJd(await send('useJd', { tabId: state.tabId, jd }))
    $('jdForm').hidden = true
  } catch (err) {
    banner(err.message)
  }
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

/** What actually happened, in the words the user needs to hear.
 *
 * A choice field's `wrote` is the option that got clicked, not the text we sent,
 * so measuring it against the answer would report a truncation that never
 * happened — "truncated to 6 of 18 characters" for a perfectly ticked box. */
function filledMessage(field, trace, res) {
  const check = ' Check it before you submit.'
  if (field.type === 'checkbox') {
    return `${res.wrote[0].toUpperCase()}${res.wrote.slice(1)}.${check}`
  }
  if (field.multi || field.type === 'radio' || field.type === 'select') {
    const missed = res.unmatched?.length ? ` No option matched ${res.unmatched.join(', ')}.` : ''
    const unsure = res.unconfirmed ? ' The page did not confirm the click.' : ''
    return `Picked "${res.wrote}".${missed}${unsure}${check}`
  }
  if (res.wrote.length < trace.answer.length) {
    return `Filled, but the page truncated it to ${res.wrote.length} of ${trace.answer.length} characters.`
  }
  return `Filled.${check}`
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
      state.results.set(field.key, { trace, filled: filledMessage(field, trace, res) })
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
  showJd(null)
  render()
}

// ── boot ──────────────────────────────────────────────────────────────────────

;(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  state.tabId = tab?.id ?? null
  await loadSettings()
  await loadJd()
  await checkHealth()
})()
