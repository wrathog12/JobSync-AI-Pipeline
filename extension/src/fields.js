/* Finding fillable fields, reading their constraints, and writing to them.
 *
 * Two rules here are not conveniences and should not be relaxed:
 *
 * **Nothing is written until the backend has classified it, and an ATTESTATION
 * field is never written at all.** The deny-list lives server-side, but the
 * *write* happens here, so this is the last place that can refuse — and the only
 * one that matters. A generated "No" to "do you require sponsorship?" is a false
 * statement on a legal document with the user's name on it.
 *
 * **Setting `.value` is not enough.** Every modern ATS is React or similar, and
 * React reads from its own state, not the DOM. Assigning `input.value` updates
 * the pixels and nothing else: the framework's state still holds "", the next
 * re-render wipes what we wrote, and validation reports the field as empty. The
 * fix is the native setter plus a bubbling `input` event, which is what a
 * keystroke actually produces.
 */

if (!window.JobSyncFields) {
  const { resolve, resolveGroup } = window.JobSyncLabels

  /** Types we will not touch, each for its own reason. */
  const SKIP_TYPES = new Set([
    'hidden',
    'submit',
    'reset',
    'button',
    'image',
    'file', // uploads need real bytes; a value assignment is impossible by design
    'password', // never
  ])

  const TYPE_MAP = {
    textarea: 'textarea',
    'select-one': 'select',
    'select-multiple': 'select',
    text: 'text',
    email: 'text',
    tel: 'text',
    url: 'text',
    search: 'text',
    number: 'number',
    date: 'date',
    month: 'date',
    checkbox: 'checkbox',
    radio: 'radio',
  }

  const typeOf = (el) => {
    if (el.tagName === 'TEXTAREA') return 'textarea'
    if (el.tagName === 'SELECT') return 'select'
    return TYPE_MAP[el.type] || 'unknown'
  }

  /** Rendered and reachable. `offsetParent` is null for anything display:none,
   * which is how multi-step forms keep later pages in the DOM — filling those
   * would write answers into a page the user has not reached. */
  const isVisible = (el) => {
    if (el.disabled || el.readOnly) return false
    if (el.type === 'hidden') return false
    const rect = el.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) return false
    return el.offsetParent !== null || getComputedStyle(el).position === 'fixed'
  }

  /** Word and character limits, wherever the page states them.
   *
   * The unit is kept rather than normalised here: 500 words and 500 characters
   * differ by about 6x, and the backend has a `LimitUnit` for exactly this. A
   * 500-word answer truncated to 500 characters is not a shorter answer, it is
   * an unusable one. */
  const LIMIT_RE = /(?:max(?:imum)?|no more than|up to|within|limit\D{0,10})?\s*(\d{2,5})\s*(characters?|chars?|words?)/i

  const constraintsOf = (el) => {
    const out = {
      max_value: null,
      min_value: null,
      unit: 'chars',
      is_required: el.required || el.getAttribute('aria-required') === 'true',
      extracted_from: null,
    }

    const attr = parseInt(el.getAttribute('maxlength') || '', 10)
    // Browsers report 524288 for "no maxlength" on some engines, and a few ATS
    // set an absurd ceiling to disable the native counter. Neither is a limit.
    if (Number.isFinite(attr) && attr > 0 && attr < 100000) {
      out.max_value = attr
      out.extracted_from = 'maxLength'
    }

    if (out.max_value === null) {
      // Helper text, which is where word limits almost always live — a "max 300
      // words" note under a textarea with no maxlength attribute at all.
      const box = el.closest('[class*="field"], [class*="question"], fieldset, label, div')
      const help = window.JobSyncLabels.textOf(box)
      const hit = LIMIT_RE.exec(help)
      if (hit) {
        out.max_value = parseInt(hit[1], 10)
        out.unit = /word/i.test(hit[2]) ? 'words' : 'chars'
        out.extracted_from = 'helper_text'
      }
    }
    return out
  }

  const optionsOf = (el) => {
    if (el.tagName === 'SELECT') {
      return [...el.options].map((o) => window.JobSyncLabels.strip(o.textContent)).filter(Boolean)
    }
    if (el.type === 'radio' && el.name) {
      // Filtered by property, not by selector: radio names carry the same
      // bracketed ATS syntax as ids, and a thrown selector here would report the
      // group as having no options at all.
      const group = el.form || document
      return [...group.querySelectorAll('input[type="radio"]')]
        .filter((r) => r.name === el.name)
        .map((r) => resolve(r).label)
        .filter(Boolean)
    }
    return []
  }

  /** id -> element, so a later fill call can find the same node without the
   * popup ever holding a DOM reference. Survives between messages because the
   * injected script stays resident on the page. */
  const registry = new Map()
  let counter = 0

  function scan() {
    registry.clear()
    counter = 0
    const seenRadioGroups = new Set()
    const fields = []

    for (const el of document.querySelectorAll('input, textarea, select')) {
      if (SKIP_TYPES.has(el.type)) continue
      if (!isVisible(el)) continue

      // One entry per radio group, not per button: the question is "which", asked
      // once, and the backend picks from `options`.
      if (el.type === 'radio') {
        if (seenRadioGroups.has(el.name)) continue
        seenRadioGroups.add(el.name)
      }

      // A radio button's own label is its *answer*, so the group asks the
      // container instead. Getting this wrong sends "Yes" as the question and the
      // real one — often a sponsorship attestation — is never classified.
      const { label, via } = el.type === 'radio' ? resolveGroup(el) : resolve(el)
      if (!label) continue // nothing to ask the backend about

      const id = `jf-${(counter += 1)}`
      registry.set(id, el)
      fields.push({
        id,
        type: typeOf(el),
        context_label: label,
        constraints: constraintsOf(el),
        options: optionsOf(el),
        // Client-side only; the backend schema does not carry these.
        label_via: via,
        current_value: (el.value || '').slice(0, 200),
      })
    }
    return { url: location.href, title: document.title, fields }
  }

  /** Write as a keystroke would, not as a script would.
   *
   * `el.value = x` shadows React's own value setter, so React never sees the
   * change: its state stays stale, the next render restores the old value, and
   * required-field validation still fails. Calling the *prototype's* setter and
   * dispatching a bubbling `input` is what the framework is listening for. */
  function setValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (setter) setter.call(el, value)
    else el.value = value
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  function selectOption(el, value) {
    const want = value.trim().toLowerCase()
    const exact = [...el.options].find((o) => o.textContent.trim().toLowerCase() === want)
    const loose =
      exact || [...el.options].find((o) => o.textContent.trim().toLowerCase().includes(want))
    if (!loose) return { ok: false, reason: `no option matching "${value}"` }
    el.value = loose.value
    el.dispatchEvent(new Event('change', { bubbles: true }))
    return { ok: true, wrote: loose.textContent.trim() }
  }

  function fill(id, value, fieldClass) {
    const el = registry.get(id)
    if (!el) return { ok: false, reason: 'that field is gone — rescan the page' }

    // The refusal that matters. The backend already declined to generate this,
    // but the write happens here, so here is where it has to be impossible.
    if (fieldClass === 'attestation') {
      return { ok: false, reason: 'attestation — you answer this one yourself' }
    }
    if (!isVisible(el)) return { ok: false, reason: 'field is no longer visible or editable' }
    if (typeof value !== 'string' || !value) return { ok: false, reason: 'nothing to write' }

    if (el.tagName === 'SELECT') return selectOption(el, value)
    if (el.type === 'checkbox' || el.type === 'radio') {
      // Deliberately not automated: a checkbox is nearly always a consent or an
      // attestation, and the ones that are not are cheap to click.
      return { ok: false, reason: 'checkboxes and radios are yours to click' }
    }

    // `maxlength` constrains typing, not assignment: a browser will happily hold
    // an over-long programmatic value and then fail constraint validation on
    // submit ("too long"), which reads as a broken form rather than as our fault.
    // Clamping here is the difference between a shorter answer and no submission.
    const cap = parseInt(el.getAttribute('maxlength') || '', 10)
    const text =
      Number.isFinite(cap) && cap > 0 && cap < value.length ? value.slice(0, cap) : value

    setValue(el, text)
    // Report what the field actually holds, not what we sent, so a truncation is
    // visible in the popup rather than at the far end of a rejected application.
    return { ok: true, wrote: el.value }
  }

  function highlight(id) {
    const el = registry.get(id)
    if (!el) return false
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const previous = el.style.outline
    el.style.outline = '2px solid #6ea8fe'
    setTimeout(() => {
      el.style.outline = previous
    }, 1500)
    return true
  }

  window.JobSyncFields = { scan, fill, highlight }
}
