/* Scanning, constraint extraction, and the two rules about writing.
 *
 * The refusals are the tests that matter here. Everything else is a convenience
 * that can be wrong without hurting anyone; filling an attestation field puts a
 * generated statement about the user's legal status on a form with their name on
 * it, and filling in a way React ignores produces an answer that looks submitted
 * and is not.
 */

import { describe, expect, it, vi } from 'vitest'
import { fill, only, page, scan } from './helpers.js'

describe('what gets scanned', () => {
  it('skips the field types that must never be touched', () => {
    page(`
      <label for="a">Cover letter</label><textarea id="a"></textarea>
      <label for="b">Password</label><input id="b" type="password" />
      <label for="c">Résumé</label><input id="c" type="file" />
      <label for="d">CSRF</label><input id="d" type="hidden" />
      <label for="e">Submit</label><input id="e" type="submit" />
    `)
    expect(scan().fields.map((f) => f.context_label)).toEqual(['Cover letter'])
  })

  it('skips fields on pages the user has not reached', () => {
    // Multi-step forms keep later pages in the DOM with display:none. Filling
    // those writes answers into a page nobody has seen, and they are submitted
    // together.
    page(`
      <div><label for="now">Current question</label><input id="now" /></div>
      <div style="display: none">
        <label for="later">Question on step 4</label><input id="later" />
      </div>
    `)
    expect(scan().fields.map((f) => f.context_label)).toEqual(['Current question'])
  })

  it('skips disabled and readonly fields', () => {
    page(`
      <label for="a">Editable</label><input id="a" />
      <label for="b">Locked</label><input id="b" disabled />
      <label for="c">Computed</label><input id="c" readonly />
    `)
    expect(scan().fields.map((f) => f.context_label)).toEqual(['Editable'])
  })

  it('asks a radio group once, not once per button', () => {
    page(`
      <fieldset>
        <legend>Do you require visa sponsorship?</legend>
        <label for="y">Yes</label><input type="radio" id="y" name="sponsor" />
        <label for="n">No</label><input type="radio" id="n" name="sponsor" />
      </fieldset>
    `)
    const { fields } = scan()
    expect(fields).toHaveLength(1)
    expect(fields[0].type).toBe('radio')
    expect(fields[0].options).toEqual(['Yes', 'No'])
    // The label is the legend, not the first button's own label. Reading "Yes" as
    // the question is worse than reading nothing: the sponsorship question never
    // reaches the deny-list, and the backend cheerfully answers "Yes".
    expect(fields[0].context_label).toBe('Do you require visa sponsorship?')
  })

  it('reports the existing value so an already-filled field is obvious', () => {
    page(`<label for="a">Email</label><input id="a" value="me@example.com" />`)
    expect(only().current_value).toBe('me@example.com')
  })
})

describe('constraints', () => {
  it('reads a maxlength attribute', () => {
    page(`<label for="a">Why us?</label><textarea id="a" maxlength="500"></textarea>`)
    expect(only().constraints).toMatchObject({
      max_value: 500,
      unit: 'chars',
      extracted_from: 'maxLength',
    })
  })

  it('ignores the sentinel maxlength browsers report for "no limit"', () => {
    page(`<label for="a">Why us?</label><textarea id="a" maxlength="524288"></textarea>`)
    expect(only().constraints.max_value).toBeNull()
  })

  it('reads a word limit out of helper text and keeps the unit', () => {
    // The unit is the point. 300 words and 300 characters differ about 6x, and a
    // 300-word answer cut to 300 characters is not shorter, it is unusable.
    page(`
      <div class="field">
        <label for="a">Tell us about yourself</label>
        <textarea id="a"></textarea>
        <p class="help">Maximum 300 words.</p>
      </div>
    `)
    expect(only().constraints).toMatchObject({
      max_value: 300,
      unit: 'words',
      extracted_from: 'helper_text',
    })
  })

  it('prefers the attribute over the prose when both are present', () => {
    page(`
      <div class="field">
        <label for="a">Why us?</label>
        <textarea id="a" maxlength="1000"></textarea>
        <p>Please keep it under 200 words.</p>
      </div>
    `)
    expect(only().constraints).toMatchObject({ max_value: 1000, unit: 'chars' })
  })

  it('picks up required from either the attribute or aria', () => {
    // Labels here are real ones, not "A"/"B"/"C": a one-character label is
    // rejected as implausible, so the whole field is skipped and the assertion
    // fails for a reason unrelated to what it is testing.
    page(`
      <label for="a">Full name</label><input id="a" required />
      <label for="b">Email address</label><input id="b" aria-required="true" />
      <label for="c">Portfolio URL</label><input id="c" />
    `)
    expect(scan().fields.map((f) => f.constraints.is_required)).toEqual([true, true, false])
  })
})

describe('writing', () => {
  it('refuses an attestation field outright', () => {
    // The refusal that matters. The backend already declined to generate this,
    // but the write happens in the page, so this is the last place that can say
    // no — and the only one that actually stops it.
    page(`<label for="a">Do you require sponsorship?</label><input id="a" />`)
    const field = only()

    const result = fill(field.id, 'No', 'attestation')

    expect(result.ok).toBe(false)
    expect(result.reason).toMatch(/attestation/)
    expect(document.querySelector('#a').value).toBe('')
  })

  it('writes through the prototype setter so React notices', () => {
    // Assigning `el.value` shadows React's own setter: the pixels update, React's
    // state does not, and the next render restores the old value while validation
    // still calls the field empty. A real keystroke produces a bubbling `input`,
    // so that is what we produce.
    page(`<label for="a">Cover letter</label><textarea id="a"></textarea>`)
    const el = document.querySelector('#a')
    const seen = []
    el.addEventListener('input', (e) => seen.push(['input', e.bubbles]))
    el.addEventListener('change', (e) => seen.push(['change', e.bubbles]))

    const result = fill(only().id, 'I shipped the thing.', 'generative')

    expect(result).toEqual({ ok: true, wrote: 'I shipped the thing.' })
    expect(seen).toEqual([
      ['input', true],
      ['change', true],
    ])
  })

  it('reports what the field kept, not what we sent', () => {
    // A maxlength the page enforces truncates silently. The user should learn
    // that from the popup, not from a rejected application.
    page(`<label for="a">Why us?</label><input id="a" maxlength="10" />`)
    const result = fill(only().id, 'far too long to fit', 'generative')
    expect(result.ok).toBe(true)
    expect(result.wrote).toBe('far too lo')
  })

  it('matches a select option by its visible text', () => {
    page(`
      <label for="a">Years of experience</label>
      <select id="a"><option>0-2</option><option>3-5</option><option>6+</option></select>
    `)
    expect(fill(only().id, '3-5', 'deterministic')).toEqual({ ok: true, wrote: '3-5' })
    expect(document.querySelector('#a').value).toBe('3-5')
  })

  it('says so rather than guessing when no option matches', () => {
    page(`
      <label for="a">Years of experience</label>
      <select id="a"><option>0-2</option><option>3-5</option></select>
    `)
    const result = fill(only().id, 'about seven', 'deterministic')
    expect(result.ok).toBe(false)
    expect(result.reason).toMatch(/no option matching/)
  })

  it('leaves checkboxes to the user', () => {
    page(`<label for="a">I certify the above is true</label><input id="a" type="checkbox" />`)
    const result = fill(only().id, 'true', 'generative')
    expect(result.ok).toBe(false)
    expect(document.querySelector('#a').checked).toBe(false)
  })

  it('fails clearly when the page has changed under it', () => {
    page(`<label for="a">Cover letter</label><textarea id="a"></textarea>`)
    const field = only()
    document.body.innerHTML = ''
    expect(fill(field.id, 'text', 'generative')).toMatchObject({ ok: false })
  })

  it('refuses an empty answer instead of clearing the field', () => {
    page(`<label for="a">Cover letter</label><textarea id="a">what I typed</textarea>`)
    const result = fill(only().id, '', 'generative')
    expect(result.ok).toBe(false)
    expect(document.querySelector('#a').value).toBe('what I typed')
  })
})

describe('highlight', () => {
  it('scrolls to a field and restores its outline', () => {
    page(`<label for="a">Cover letter</label><textarea id="a" style="outline: none"></textarea>`)
    const el = document.querySelector('#a')
    el.scrollIntoView = vi.fn()

    expect(window.JobSyncFields.highlight(only().id)).toBe(true)
    expect(el.scrollIntoView).toHaveBeenCalled()
    expect(el.style.outline).toBe('2px solid #6ea8fe')
  })
})
