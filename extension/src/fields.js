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
 *
 * ── Why this looks for more than `input, textarea, select` ────────────────────
 *
 * Because on a lot of real forms there is no `<input>` to find. Google Forms
 * builds every radio and dropdown out of `<div>`s carrying ARIA roles, and
 * Microsoft Forms does the same for most of its answer types. A scan that only
 * asks for native controls returns *zero fields* on a Google Form with eight
 * questions on it — not a wrong answer, no answer at all.
 *
 * So the candidate set is native controls **plus** the ARIA widget roles that
 * mean "this is a form control", plus `contenteditable`, and the whole search
 * descends through shadow roots because Workday and most web-component design
 * systems put their inputs inside one.
 *
 * The ARIA roles are not a guess: they are the contract a form has to honour for
 * a screen reader to work at all. Anything a blind user can fill in, this can
 * find. That makes it a far better net than pattern-matching each ATS's class
 * names, which change without notice.
 */

if (!window.JobSyncFields) {
  const { resolve, resolveGroup, strip, textOf, rootOf } = window.JobSyncLabels

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

  /** ARIA roles that mean "form control", mapped to the backend's `FieldType`. */
  const ROLE_TYPE = {
    radiogroup: 'radio',
    radio: 'radio',
    checkbox: 'checkbox',
    switch: 'checkbox',
    combobox: 'select',
    listbox: 'select',
    textbox: 'textarea',
    spinbutton: 'number',
  }

  const NATIVE = 'input, textarea, select'
  const ROLES = Object.keys(ROLE_TYPE)
    .map((r) => `[role="${r}"]`)
    .join(', ')
  const EDITABLE = '[contenteditable=""], [contenteditable="true"]'
  const CANDIDATES = `${NATIVE}, ${ROLES}, ${EDITABLE}`

  /** `querySelectorAll` that also descends into shadow roots.
   *
   * Workday, Salesforce and most web-component design systems put their inputs
   * inside a shadow root, where an ordinary query cannot see them — the page
   * looks empty and the extension reports no fields on a form that plainly has
   * some. Open shadow roots are reachable; closed ones are not, and nothing can
   * change that from a content script. */
  function deepQueryAll(selector, root = document) {
    const found = new Set()
    const visit = (node) => {
      for (const el of node.querySelectorAll(selector)) found.add(el)
      for (const el of node.querySelectorAll('*')) if (el.shadowRoot) visit(el.shadowRoot)
    }
    visit(root)
    return [...found]
  }

  const isNative = (el) => el.matches(NATIVE)
  const roleOf = (el) => (el.getAttribute('role') || '').toLowerCase()
  const isEditable = (el) => el.isContentEditable === true || el.matches(EDITABLE)

  function typeOf(el) {
    if (el.tagName === 'TEXTAREA') return 'textarea'
    if (el.tagName === 'SELECT') return 'select'
    if (el.tagName === 'INPUT') return TYPE_MAP[el.type] || 'unknown'
    const role = ROLE_TYPE[roleOf(el)]
    if (role) return role
    if (isEditable(el)) return 'textarea'
    return 'unknown'
  }

  /** Rendered and reachable. `offsetParent` is null for anything display:none,
   * which is how multi-step forms keep later pages in the DOM — filling those
   * would write answers into a page the user has not reached.
   *
   * `aria-disabled` is checked alongside the real `disabled` property because a
   * div pretending to be an input has no `disabled` property to check, and a
   * greyed-out ARIA control is exactly as unfillable as a greyed-out `<input>`. */
  const isVisible = (el) => {
    if (el.disabled || el.readOnly) return false
    if (el.getAttribute('aria-disabled') === 'true') return false
    if (el.getAttribute('aria-hidden') === 'true') return false
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
      is_required: Boolean(el.required) || el.getAttribute('aria-required') === 'true',
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
      const help = textOf(box)
      const hit = LIMIT_RE.exec(help)
      if (hit) {
        out.max_value = parseInt(hit[1], 10)
        out.unit = /word/i.test(hit[2]) ? 'words' : 'chars'
        out.extracted_from = 'helper_text'
      }
    }
    return out
  }

  // ── options ─────────────────────────────────────────────────────────────────

  /** One choice's visible text. ARIA widgets carry it in `aria-label` or
   * `data-value` far more often than as child text — Google Forms uses both. */
  const optionLabel = (el) =>
    strip(el.getAttribute('aria-label')) ||
    strip(el.getAttribute('data-value')) ||
    textOf(el) ||
    resolve(el).label

  /** The individual buttons of a radio question, whatever they are made of.
   *
   * `el` is whatever `scan` decided *is* the question — a `[role="radiogroup"]`,
   * a `<fieldset>`, or (when the page gave us nothing to group by) one native
   * radio standing in for its whole named group. */
  function radioButtons(el) {
    if (isNative(el) && el.type === 'radio') {
      // `getRootNode` rather than `document`: inside a shadow root, `document`
      // cannot see the sibling buttons at all.
      const root = el.form || el.getRootNode()
      const all = [...root.querySelectorAll('input[type="radio"]')]
      return el.name ? all.filter((r) => r.name === el.name) : [el]
    }
    const aria = [...el.querySelectorAll('[role="radio"]')]
    return aria.length ? aria : [...el.querySelectorAll('input[type="radio"]')]
  }

  /** The choices of a select-like field. An ARIA combobox usually renders its
   * options only once opened, and often into a portal at the end of `<body>`
   * rather than inside itself — so an empty list here means "not yet known",
   * not "no choices". */
  function selectOptions(el) {
    if (el.tagName === 'SELECT') return [...el.options].map((o) => strip(o.textContent))
    const owned = el.getAttribute('aria-controls') || el.getAttribute('aria-owns')
    const root = rootOf(el)
    const box = (owned && root.querySelector(`[id="${owned}"]`)) || el
    return [...box.querySelectorAll('[role="option"]')].map(optionLabel)
  }

  function optionsOf(el, type) {
    if (type === 'radio') return radioButtons(el).map(optionLabel).filter(Boolean)
    if (type === 'select') return selectOptions(el).filter(Boolean)
    return []
  }

  /** What the field already holds, so an answered question is obvious. */
  function currentValue(el, type) {
    if (type === 'radio') {
      const picked = radioButtons(el).find(
        (r) => r.checked || r.getAttribute('aria-checked') === 'true'
      )
      return picked ? optionLabel(picked) : ''
    }
    if (type === 'checkbox') {
      const on = el.checked || el.getAttribute('aria-checked') === 'true'
      return on ? 'checked' : ''
    }
    if (isEditable(el) && !isNative(el)) return strip(el.textContent)
    return strip(el.value || '')
  }

  // ── what counts as one question ──────────────────────────────────────────────

  /** The combobox that points at this listbox, if any. Matched by comparing the
   * attribute rather than by building an `[aria-controls="…"]` selector, because
   * generated ids contain characters that are selector syntax and the throw would
   * be silent. Only a `combobox` counts, which also guarantees `asField` cannot
   * recurse forever. */
  function comboboxOwning(el) {
    if (!el.id) return null
    for (const cand of rootOf(el).querySelectorAll('[role="combobox"]')) {
      const owns = cand.getAttribute('aria-controls') || cand.getAttribute('aria-owns')
      if (owns === el.id) return cand
    }
    return null
  }

  /** Maps a candidate element onto the *question* it belongs to.
   *
   * `key` is what deduplicates: every radio in a group, and the group container
   * itself, all produce the same key, so the question is asked once.
   *
   * `el` and `box` are different things, and conflating them is the bug this
   * separation exists to prevent. `el` is what gets written to; `box` is where
   * the choices live. On a searchable dropdown those are two different elements
   * — a wrapper carrying the role and the options, and an `<input>` carrying the
   * text — so registering only the wrapper gives a question that cannot be typed
   * into, and registering only the input gives one with no options to pick from.
   */
  function asField(el) {
    const role = roleOf(el)

    if (role === 'radiogroup') return { el, box: el, type: 'radio', key: el }

    if (role === 'radio') {
      const group = el.closest('[role="radiogroup"], [role="group"], fieldset')
      const box = group || el.parentElement || el
      return { el: box, box, type: 'radio', key: box }
    }

    if (isNative(el) && el.type === 'radio') {
      const group = el.closest('[role="radiogroup"]')
      if (group) return { el: group, box: group, type: 'radio', key: group }
      const key = el.name ? `radio:${el.name}` : el.parentElement || el
      return { el, box: el, type: 'radio', key }
    }

    // A searchable dropdown is usually a combobox plus the listbox it points at
    // via `aria-controls`. Both are candidates, so without this the user is asked
    // the same question twice — once for the box and once for its own menu.
    if (role === 'listbox') {
      const owner = comboboxOwning(el)
      if (owner) return asField(owner)
    }

    if (role === 'combobox' || role === 'listbox') {
      const inner = el.querySelector('input:not([type="hidden"]), textarea')
      return { el: inner || el, box: el, type: 'select', key: el }
    }

    const combo = el.closest('[role="combobox"], [role="listbox"]')
    if (combo && combo !== el) return { el, box: combo, type: 'select', key: combo }

    return { el, box: el, type: typeOf(el), key: el }
  }

  /** id -> {el, box, type}, so a later fill call can find the same nodes without
   * the popup ever holding a DOM reference. Survives between messages because the
   * injected script stays resident on the page. */
  const registry = new Map()
  let counter = 0

  function scan() {
    registry.clear()
    counter = 0
    const seen = new Set()
    const fields = []

    for (const candidate of deepQueryAll(CANDIDATES)) {
      if (isNative(candidate) && SKIP_TYPES.has(candidate.type)) continue
      if (!isVisible(candidate)) continue

      const { el, box, type, key } = asField(candidate)
      if (seen.has(key)) continue
      seen.add(key)

      // A radio button's own label is its *answer*, so the group asks the
      // container instead. Getting this wrong sends "Yes" as the question and the
      // real one — often a sponsorship attestation — is never classified.
      const { label, via } = type === 'radio' ? resolveGroup(box) : resolve(el)
      if (!label) continue // nothing to ask the backend about

      const id = `jf-${(counter += 1)}`
      registry.set(id, { el, box, type })
      fields.push({
        id,
        type,
        context_label: label,
        constraints: constraintsOf(el),
        options: optionsOf(box, type),
        // Client-side only; the backend schema does not carry these.
        label_via: via,
        current_value: currentValue(box, type).slice(0, 200),
      })
    }
    return { url: location.href, title: document.title, fields }
  }

  // ── writing ──────────────────────────────────────────────────────────────────

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

  function setEditable(el, value) {
    el.focus?.()
    el.textContent = value
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
    const entry = registry.get(id)
    if (!entry) return { ok: false, reason: 'that field is gone — rescan the page' }
    const { el, type } = entry

    // The refusal that matters. The backend already declined to generate this,
    // but the write happens here, so here is where it has to be impossible.
    if (fieldClass === 'attestation') {
      return { ok: false, reason: 'attestation — you answer this one yourself' }
    }
    if (!isVisible(el)) return { ok: false, reason: 'field is no longer visible or editable' }
    if (typeof value !== 'string' || !value) return { ok: false, reason: 'nothing to write' }

    if (el.tagName === 'SELECT') return selectOption(el, value)
    if (type === 'radio' || type === 'checkbox') {
      return { ok: false, reason: 'choices are yours to click' }
    }
    if (type === 'select') {
      return { ok: false, reason: 'this dropdown has to be opened by hand' }
    }

    if (isEditable(el) && !isNative(el)) {
      setEditable(el, value)
      return { ok: true, wrote: strip(el.textContent) }
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
    const entry = registry.get(id)
    if (!entry) return false
    const { el } = entry
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
