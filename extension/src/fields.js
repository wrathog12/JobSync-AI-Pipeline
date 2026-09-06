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
 * **A choice is made by clicking, and then read back.** There is no way to "set"
 * a div that is pretending to be a radio button, and setting `.checked` on a real
 * one leaves the framework unaware, so clicking is not a shortcut here — it is the
 * only correct move. What makes it safe is the read-back: every click is verified
 * against what the widget now says, and a click the page ignored is reported as a
 * failure rather than as an answer the user never gave. That is why `fill` is
 * async — a dropdown's options do not exist until it is opened.
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

  /** The tickboxes of a "select all that apply". */
  const checkboxes = (el) => {
    const aria = [...el.querySelectorAll('[role="checkbox"], [role="switch"]')]
    return aria.length ? aria : [...el.querySelectorAll('input[type="checkbox"]')]
  }

  /** Where a select-like widget keeps its options. Usually *not* inside itself: a
   * combobox points at its listbox with `aria-controls`, and react-select renders
   * the menu into a portal at the end of `<body>`. */
  function optionHolder(el) {
    const owned = el.getAttribute('aria-controls') || el.getAttribute('aria-owns')
    const root = rootOf(el)
    return (owned && root.querySelector(`[id="${owned}"]`)) || el
  }

  /** The option elements of a select-like field.
   *
   * An empty list means "not yet known", not "no choices" — an ARIA combobox
   * usually renders nothing at all until it is opened. `anywhere` is for the
   * moment *after* opening, when the menu may have been portalled clean out of
   * the widget: it is only safe while exactly one menu is open on the page, since
   * otherwise we would be reading some other field's choices. */
  function optionNodes(el, anywhere = false) {
    const inside = [...optionHolder(el).querySelectorAll('[role="option"]')]
    if (inside.length || !anywhere) return inside
    const open = deepQueryAll('[role="listbox"], [role="menu"]').filter(isVisible)
    return open.length === 1 ? [...open[0].querySelectorAll('[role="option"]')] : []
  }

  /** Ticked, by whatever means this widget records it.
   *
   * A native control has `.checked`, a div has `aria-checked`, and a few design
   * systems record it in a class name and nothing else. Reading only `.checked`
   * makes every ARIA radio look permanently unselected, so a fill can never
   * confirm it worked and reports a failure on a form it filled correctly. */
  const isChecked = (el) => {
    if (el.checked === true) return true
    const aria = el.getAttribute('aria-checked') || el.getAttribute('aria-selected')
    if (aria === 'true') return true
    if (aria === 'false') return false
    if (el.checked === false) return false
    const cls = typeof el.className === 'string' ? el.className : ''
    return /(^|[-_ ])(checked|selected)([-_ ]|$)/.test(cls)
  }

  function optionsOf(box, type, multi) {
    if (type === 'radio') return radioButtons(box).map(optionLabel).filter(Boolean)
    if (multi) return checkboxes(box).map(optionLabel).filter(Boolean)
    if (type === 'select') {
      if (box.tagName === 'SELECT') {
        return [...box.options].map((o) => strip(o.textContent)).filter(Boolean)
      }
      return optionNodes(box).map(optionLabel).filter(Boolean)
    }
    return []
  }

  /** What the field already holds, so an answered question is obvious. */
  function currentValue(box, type, multi) {
    if (type === 'radio') {
      const picked = radioButtons(box).find(isChecked)
      return picked ? optionLabel(picked) : ''
    }
    if (multi) {
      return checkboxes(box).filter(isChecked).map(optionLabel).join(', ')
    }
    if (type === 'checkbox') return isChecked(box) ? 'checked' : ''
    if (isEditable(box) && !isNative(box)) return strip(box.textContent)
    return strip(box.value || '')
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

  /** Containers a "select all that apply" can live in.
   *
   * Deliberately no bare `div`: every checkbox on a page has *some* div around it,
   * and merging two unrelated consent boxes into one question invents a question
   * nobody asked and then answers it. */
  const CHECK_GROUP =
    'fieldset, [role="group"], [role="listitem"], [data-automation-id="questionContent"],' +
    '[class*="checkbox-group"], [class*="question"]'

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

    // Several boxes under one heading are a "select all that apply", and the
    // question is the heading — each box's own label is one of the *answers*, the
    // same trap as a radio group. One box on its own is its own question ("I have
    // a valid work permit"), which is why the count decides and not the container.
    if (role === 'checkbox' || role === 'switch' || (isNative(el) && el.type === 'checkbox')) {
      const group = el.closest(CHECK_GROUP)
      if (group && checkboxes(group).length > 1) {
        return { el: group, box: group, type: 'select', key: group, multi: true }
      }
      return { el, box: el, type: 'checkbox', key: el }
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

  /** id -> {el, box, type, multi}, so a later fill call can find the same nodes without
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

      const { el, box, type, key, multi } = asField(candidate)
      if (seen.has(key)) continue
      seen.add(key)

      // A radio button's own label is its *answer*, so the group asks the
      // container instead. Getting this wrong sends "Yes" as the question and the
      // real one — often a sponsorship attestation — is never classified.
      const { label, via } = type === 'radio' || multi ? resolveGroup(box) : resolve(el)
      if (!label) continue // nothing to ask the backend about

      const id = `jf-${(counter += 1)}`
      registry.set(id, { el, box, type, multi })
      fields.push({
        id,
        type,
        context_label: label,
        constraints: constraintsOf(el),
        options: optionsOf(box, type, multi),
        // Client-side only; the backend schema does not carry these.
        label_via: via,
        multi: Boolean(multi),
        current_value: currentValue(box, type, multi).slice(0, 200),
      })
    }
    return { url: location.href, title: document.title, fields }
  }

  // ── matching an answer to one of the offered choices ─────────────────────────

  /** Comparable form: case, punctuation and decoration gone. `+` and `-` survive
   * because "6+" and "3-5" are real options and are the whole difference. */
  const norm = (s) =>
    strip(s)
      .toLowerCase()
      .replace(/[^a-z0-9+\- ]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  const AFFIRM = /^(yes|y|true|yeah|agree|accept|confirm|correct|i (do|am|have|will|agree|accept|confirm))\b/
  const DENY = /^(no|n|not|none|false|never|decline|disagree|i (do not|dont|am not|have not|will not))\b/

  /** Which choice an answer means, or -1.
   *
   * Ordered exact-to-loose, because a wrong pick is worse than no pick: the user
   * reads "filled" and never looks at it again, and the wrong answer is the one
   * that gets submitted. Containment is word-level rather than substring for the
   * same reason — "no" is a substring of "Not applicable", and picking that for an
   * answer of "No" is exactly the error nobody catches. */
  function matchIndex(labels, value) {
    const want = norm(value)
    if (!want) return -1
    const options = labels.map(norm)

    const tests = [
      (o) => o === want,
      (o) => o.startsWith(`${want} `),
      (o) => o.split(' ').includes(want),
      (o) => want.length >= 4 && o.includes(want),
      (o) => o.length >= 4 && want.includes(o),
    ]
    for (const test of tests) {
      const hit = options.findIndex(test)
      if (hit !== -1) return hit
    }

    // A plain "Yes" against options written out as "I am authorised to work here".
    const family = AFFIRM.test(want) ? AFFIRM : DENY.test(want) ? DENY : null
    if (family) {
      const hit = options.findIndex((o) => family.test(o))
      if (hit !== -1) return hit
    }
    return -1
  }

  // ── clicking ─────────────────────────────────────────────────────────────────

  const sleep = (ms) => new Promise((done) => setTimeout(done, ms))

  /** Poll until `fn` returns something truthy, or give up.
   *
   * Waiting is unavoidable for anything with a menu: the options do not exist
   * until the widget is opened, and the framework renders them a frame or two
   * later, so at the moment of the click there is nothing to click. This works
   * only because `chrome.scripting.executeScript` awaits a promise the injected
   * function returns — otherwise the answer would arrive after the popup had
   * already been told the fill failed. */
  async function waitFor(fn, timeout = 800, step = 40) {
    const deadline = Date.now() + timeout
    for (;;) {
      const value = fn()
      if (value) return value
      if (Date.now() >= deadline) return null
      await sleep(step)
    }
  }

  const fire = (el, type, Ctor, extra) => {
    if (!Ctor) return
    el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, ...extra }))
  }

  /** Ways of pressing a control, cheapest first.
   *
   * `.click()` is how a real click ends and is enough for most widgets. Some
   * design systems only listen for the pointer sequence, and some only for Space
   * on a focused control — that path always exists, because a keyboard user has to
   * be able to tick the box too. */
  const PRESSES = [
    (el) => el.click?.(),
    (el) => {
      for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) {
        fire(el, type, /^pointer/.test(type) ? window.PointerEvent : window.MouseEvent)
      }
    },
    (el) => {
      for (const type of ['keydown', 'keyup']) {
        fire(el, type, window.KeyboardEvent, { key: ' ', code: 'Space', keyCode: 32 })
      }
    },
  ]

  /** Press until `done()` agrees it worked, then stop.
   *
   * Verifying between attempts is not politeness: a widget that reacted to the
   * first press must not be pressed again, because a second press on a checkbox
   * unticks it and on a dropdown closes it. */
  async function pressUntil(el, done) {
    if (done()) return true
    el.scrollIntoView?.({ block: 'center' })
    for (const press of PRESSES) {
      el.focus?.()
      press(el)
      if (await waitFor(done, 300)) return true
    }
    return false
  }

  // ── writing ──────────────────────────────────────────────────────────────────

  const PROTO = (el) =>
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype

  /** Write as a keystroke would, not as a script would.
   *
   * `el.value = x` shadows React's own value setter, so React never sees the
   * change: its state stays stale, the next render restores the old value, and
   * required-field validation still fails. Calling the *prototype's* setter and
   * dispatching a bubbling `input` is what the framework is listening for. */
  function setValue(el, value) {
    const setter = Object.getOwnPropertyDescriptor(PROTO(el), 'value')?.set
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

  const offered = (labels) =>
    labels.length <= 12 ? labels.join(' / ') : `${labels.slice(0, 12).join(' / ')} …`

  const noMatch = (labels, value) => ({
    ok: false,
    reason: `no option matching "${value}" — offered: ${offered(labels)}`,
  })

  function selectOption(el, value) {
    const options = [...el.options]
    const pick = matchIndex(options.map((o) => o.textContent), value)
    if (pick === -1) return noMatch(options.map((o) => strip(o.textContent)), value)
    setValue(el, options[pick].value)
    return { ok: true, wrote: strip(options[pick].textContent) }
  }

  /** Pick one of a radio group's buttons by clicking it, like the user would.
   *
   * There is no way to "set" a div radio, and setting `.checked` on a native one
   * leaves the framework unaware, so a click is not a shortcut here — it is the
   * only correct move. What makes it safe is that the choice is read back
   * afterwards: a click the page ignored is reported as a failure rather than as
   * an answer the user never gave. */
  async function fillRadio(entry, value) {
    const buttons = radioButtons(entry.box)
    if (!buttons.length) return { ok: false, reason: 'no options found to click' }
    const labels = buttons.map(optionLabel)
    const pick = matchIndex(labels, value)
    if (pick === -1) return noMatch(labels, value)

    const target = buttons[pick]
    if (await pressUntil(target, () => isChecked(target))) {
      return { ok: true, wrote: labels[pick] }
    }
    return { ok: false, reason: `clicked "${labels[pick]}" but the form did not take it` }
  }

  /** A lone checkbox, which is a yes/no question wearing a different hat.
   *
   * Anything that is not recognisably a yes or a no is refused rather than
   * guessed: a tick is a claim, and "it depends" is not a tick. */
  async function fillCheckbox(entry, value) {
    const { el } = entry
    const answer = norm(value)
    const want = AFFIRM.test(answer) ? true : DENY.test(answer) ? false : null
    if (want === null) {
      return { ok: false, reason: `"${value}" is not a yes or a no — tick this one yourself` }
    }
    if (isChecked(el) === want) return { ok: true, wrote: want ? 'already ticked' : 'left unticked' }
    if (await pressUntil(el, () => isChecked(el) === want)) {
      return { ok: true, wrote: want ? 'ticked' : 'unticked' }
    }
    return { ok: false, reason: 'clicked it, but the box did not change' }
  }

  /** "Select all that apply", where the answer is a list.
   *
   * Boxes the answer did not name are left exactly as they are, never unticked:
   * an unticked box may be a choice the user made by hand, and silently removing
   * it is worse than leaving one too many. Anything in the answer that matched no
   * option is named in the result, because a partial fill the user believes is
   * complete is the failure mode here. */
  async function fillChecks(entry, value) {
    const boxes = checkboxes(entry.box)
    if (!boxes.length) return { ok: false, reason: 'no options found to tick' }
    const labels = boxes.map(optionLabel)

    const picks = new Set()
    const missed = []
    for (const part of value.split(/[,;\n•]|\s+and\s+/).map((s) => s.trim())) {
      if (!part) continue
      const hit = matchIndex(labels, part)
      if (hit === -1) missed.push(part)
      else picks.add(hit)
    }
    if (!picks.size) return noMatch(labels, value)

    const wrote = []
    for (const index of picks) {
      if (await pressUntil(boxes[index], () => isChecked(boxes[index]))) wrote.push(labels[index])
    }
    if (!wrote.length) return { ok: false, reason: 'clicked, but nothing was ticked' }
    return {
      ok: true,
      wrote: wrote.join(', '),
      ...(missed.length ? { unmatched: missed } : {}),
    }
  }

  /** A dropdown built out of divs: open it, wait for the menu, click a choice.
   *
   * Three separate things can go wrong and each is reported rather than papered
   * over — it would not open, nothing matched, or the click could not be confirmed.
   * The last one is not treated as a failure: plenty of widgets record the choice
   * somewhere unreadable, and telling the user a correct fill failed sends them
   * to redo work that is already done. */
  async function fillCombo(entry, value) {
    const { el, box } = entry
    const menu = () => {
      const nodes = optionNodes(box, true)
      return nodes.length ? nodes : null
    }

    let nodes = menu()
    if (!nodes) {
      await pressUntil(el, () => Boolean(menu()))
      nodes = menu()
    }
    // react-select and friends render no menu until a query narrows the list, so
    // typing the answer is the only way to make the options exist.
    if (!nodes && isNative(el) && el.tagName !== 'SELECT') {
      setValue(el, value)
      nodes = await waitFor(menu)
    }
    if (!nodes) return { ok: false, reason: 'the dropdown would not open — pick this one by hand' }

    const labels = nodes.map(optionLabel)
    const pick = matchIndex(labels, value)
    if (pick === -1) return noMatch(labels, value)

    const target = nodes[pick]
    const chosen = labels[pick]
    // No single flag says "this is the value now", so the check is whichever of
    // the three a given widget actually updates.
    const took = () =>
      isChecked(target) || norm(`${el.value || ''} ${textOf(box)}`).includes(norm(chosen))

    if (await pressUntil(target, took)) return { ok: true, wrote: chosen }
    return { ok: true, wrote: chosen, unconfirmed: true }
  }

  async function fill(id, value, fieldClass) {
    const entry = registry.get(id)
    if (!entry) return { ok: false, reason: 'that field is gone — rescan the page' }
    const { el, type, multi } = entry

    // The refusal that matters. The backend already declined to generate this,
    // but the write happens here, so here is where it has to be impossible.
    if (fieldClass === 'attestation') {
      return { ok: false, reason: 'attestation — you answer this one yourself' }
    }
    if (!isVisible(el)) return { ok: false, reason: 'field is no longer visible or editable' }
    if (typeof value !== 'string' || !value) return { ok: false, reason: 'nothing to write' }

    if (multi) return fillChecks(entry, value)
    if (type === 'radio') return fillRadio(entry, value)
    if (type === 'checkbox') return fillCheckbox(entry, value)
    if (el.tagName === 'SELECT') return selectOption(el, value)
    if (type === 'select') return fillCombo(entry, value)

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
