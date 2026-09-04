/* Working out what a form field is actually asking.
 *
 * This is the part that decides whether any of the rest works. The backend is
 * good at "given this question, what is the answer" and has no idea what a DOM
 * is — `FormField.context_label` is the entire interface. Send it "Question 4"
 * and the classifier falls through to ATTESTATION, which is correct behaviour
 * and a useless product.
 *
 * Real ATS pages label fields in mutually exclusive ways:
 *
 *   Greenhouse   <label for="job_application_answers_attributes_0_text_value">
 *   Lever        <label class="application-label"><span>Why us?</span><textarea>
 *   Workday      <div data-automation-id="formField-..."><label>…  (no `for`)
 *   Ashby        aria-labelledby pointing at a heading two levels up
 *   Custom React a <div> that merely sits above the input
 *
 * So this is an ordered cascade, cheapest and most reliable first, and it stops
 * at the first source that yields something. The order is the opinion here:
 *
 *   `placeholder` comes near the end, because on real forms it is usually an
 *   *example answer* ("e.g. 5 years") rather than a label, and treating an
 *   example as the question sends the classifier looking for the wrong thing.
 *
 *   `name` is last and de-camelised, because `workAuthorizationStatus` is a
 *   genuinely useful hint and `field_7b2` is not — but either beats nothing,
 *   since the deny-list matches on text and would rather see a bad label than
 *   an empty one. Failing to ATTESTATION on a real sponsorship question because
 *   we sent "" is the outcome to avoid.
 */

if (!window.JobSyncLabels) {
  const clean = (s) =>
    (s || '')
      .replace(/ /g, ' ')
      .replace(/\s+/g, ' ')
      .trim()

  /** Label text minus the noise every ATS decorates it with. */
  const strip = (s) =>
    clean(s)
      .replace(/[*✱]+/g, ' ')
      .replace(/\((required|optional)\)/gi, ' ')
      .replace(/\b(required|optional)\b\s*$/i, '')
      .replace(/\s*[:：]\s*$/, '')
      .replace(/\s+/g, ' ')
      .trim()

  /** Text of an element with form controls and their values removed.
   *
   * A wrapping `<label>` contains the input; on a `<select>` that means every
   * option's text is part of `textContent`, so the "label" for a country
   * dropdown comes back as the question plus 200 country names. */
  const textOf = (el) => {
    if (!el) return ''
    const copy = el.cloneNode(true)
    copy
      .querySelectorAll('input, textarea, select, button, option, svg, script, style')
      .forEach((n) => n.remove())
    return strip(copy.textContent)
  }

  /** Long enough to be a question, short enough not to be the whole page. */
  const plausible = (s) => s.length >= 2 && s.length <= 300

  /** Matched by attribute rather than by selector.
   *
   * `label[for="job_application[answers][0][text]"]` is a Greenhouse id inside a
   * selector, and brackets are selector syntax. `CSS.escape` handles it, but it
   * is not universally present, and when it is missing the whole thing throws and
   * the cascade silently falls through to guessing from `name`. Comparing the
   * attribute cannot be broken by whatever an ATS puts in an id. */
  const byFor = (el) => {
    if (!el.id) return ''
    const labels = document.querySelectorAll('label[for]')
    for (const label of labels) {
      if (label.getAttribute('for') === el.id) return textOf(label)
    }
    return ''
  }

  const byAncestorLabel = (el) => textOf(el.closest('label'))

  const byAriaLabelledBy = (el) => {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
    return strip(ids.map((id) => textOf(document.getElementById(id))).join(' '))
  }

  const byAriaLabel = (el) => strip(el.getAttribute('aria-label'))

  /** Containers that ATS platforms wrap one question in. Checked before generic
   * DOM walking because a hit here is the whole question and nothing else —
   * including the helper text that carries the word limit. */
  const QUESTION_CONTAINERS = [
    '[data-automation-id^="formField"]', // Workday
    '.application-question', // Lever
    '.field', // Greenhouse
    '[class*="application-field"]',
    '[class*="question"]',
    'fieldset',
  ]

  const byQuestionContainer = (el) => {
    for (const selector of QUESTION_CONTAINERS) {
      const box = el.closest(selector)
      if (!box) continue
      // The container's own label element first — its full text may include
      // helper paragraphs, and those belong to the constraints, not the question.
      const label = box.querySelector('label, legend, [class*="label"]')
      const text = textOf(label) || textOf(box)
      if (plausible(text)) return text
    }
    return ''
  }

  /** The last resort before attributes: whatever readable text sits immediately
   * before the input. Walks up, because the text is often a sibling of an
   * ancestor rather than of the input itself. */
  const byPrecedingText = (el) => {
    let node = el
    for (let depth = 0; node && depth < 4; depth += 1) {
      let sib = node.previousElementSibling
      while (sib) {
        if (!sib.matches('input, textarea, select, script, style')) {
          const text = textOf(sib)
          if (plausible(text)) return text
        }
        sib = sib.previousElementSibling
      }
      node = node.parentElement
    }
    return ''
  }

  const byAttribute = (el) => {
    const placeholder = strip(el.getAttribute('placeholder'))
    if (plausible(placeholder)) return placeholder
    const name = el.getAttribute('name') || el.id || ''
    return strip(
      name
        .replace(/[[\]_.-]+/g, ' ')
        .replace(/([a-z\d])([A-Z])/g, '$1 $2')
        .replace(/\b\d+\b/g, ' ')
    )
  }

  const SOURCES = [
    ['label_for', byFor],
    ['label_ancestor', byAncestorLabel],
    ['aria_labelledby', byAriaLabelledBy],
    ['aria_label', byAriaLabel],
    ['question_container', byQuestionContainer],
    ['preceding_text', byPrecedingText],
    ['attribute', byAttribute],
  ]

  /** For a radio group, where the per-button label is the *answer*.
   *
   * `<legend>Do you require sponsorship?</legend>` with `<label>Yes</label>` and
   * `<label>No</label>` inside: running the normal cascade on the first button
   * returns "Yes", so the backend is asked to answer the question "Yes" and the
   * real question — which is on the deny-list — is never seen. So the two
   * label-element sources are skipped here, because on a group they are
   * guaranteed to be wrong rather than merely unreliable.
   */
  const GROUP_SOURCES = [
    ['legend', (el) => textOf(el.closest('fieldset')?.querySelector('legend'))],
    ['aria_labelledby', byAriaLabelledBy],
    ['role_group', (el) => byAriaLabel(el.closest('[role="radiogroup"], [role="group"]') || el)],
    ['question_container', byQuestionContainer],
    ['preceding_text', byPrecedingText],
    ['attribute', byAttribute],
  ]

  function walk(sources, el) {
    for (const [via, fn] of sources) {
      let text = ''
      try {
        text = fn(el)
      } catch {
        // A single malformed selector or detached node must not stop the cascade.
        continue
      }
      if (plausible(text)) return { label: text, via }
    }
    return { label: '', via: 'none' }
  }

  /** Returns `{ label, via }`. `via` is reported all the way to the popup: when a
   * field is misread, the first useful question is which source produced it. */
  const resolve = (el) => walk(SOURCES, el)
  const resolveGroup = (el) => walk(GROUP_SOURCES, el)

  window.JobSyncLabels = { resolve, resolveGroup, clean, strip, textOf, plausible }
}
