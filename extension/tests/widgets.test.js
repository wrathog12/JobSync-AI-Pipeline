/* Forms that contain no `<input>` worth finding.
 *
 * Google Forms builds every radio and dropdown out of `<div>`s with ARIA roles.
 * Microsoft Forms does the same for most answer types. Workday and most
 * web-component design systems put their real inputs inside a shadow root. On
 * all three, a scan restricted to `input, textarea, select` in the light DOM
 * returns *zero fields* for a form with eight questions on it — and zero fields
 * is the failure that looks like the extension is broken, because it is.
 *
 * These fixtures are the shapes those products actually emit.
 */

import { describe, expect, it } from 'vitest'
import { only, page, scan, shadow } from './helpers.js'

describe('Google Forms', () => {
  it('finds a radio group made entirely of divs', () => {
    page(`
      <div role="listitem">
        <div id="q1" role="heading" aria-level="3"><span>Which team are you applying to?</span></div>
        <div role="radiogroup" aria-labelledby="q1">
          <div role="radio" aria-label="Engineering" data-value="Engineering"></div>
          <div role="radio" aria-label="Design" data-value="Design"></div>
          <div role="radio" aria-label="Research" data-value="Research"></div>
        </div>
      </div>
    `)
    const field = only()
    expect(field.type).toBe('radio')
    expect(field.context_label).toBe('Which team are you applying to?')
    expect(field.options).toEqual(['Engineering', 'Design', 'Research'])
  })

  it('asks the group once, not once per option div', () => {
    // Four candidate elements — the radiogroup and its three radios — collapse to
    // one question. Without the grouping the user is asked "Engineering?",
    // "Design?" and "Research?" as three separate questions.
    page(`
      <div role="listitem">
        <div id="q" role="heading">Preferred location</div>
        <div role="radiogroup" aria-labelledby="q">
          <div role="radio" aria-label="London"></div>
          <div role="radio" aria-label="Berlin"></div>
        </div>
      </div>
    `)
    expect(scan().fields).toHaveLength(1)
  })

  it('reads the question from the heading when there is no aria-labelledby', () => {
    page(`
      <div role="listitem">
        <div role="heading">Do you have a portfolio?</div>
        <div role="radiogroup">
          <div role="radio" aria-label="Yes"></div>
          <div role="radio" aria-label="No"></div>
        </div>
      </div>
    `)
    expect(only().context_label).toBe('Do you have a portfolio?')
  })

  it('does not read the answers as part of the question', () => {
    // The same bug as a <select> swallowing its options, in ARIA form: the
    // radiogroup's own text is the question followed by every answer to it.
    page(`
      <div role="listitem">
        <div role="radiogroup">
          <span>Are you willing to relocate?</span>
          <div role="radio">Yes, anywhere</div>
          <div role="radio">Only within Europe</div>
          <div role="radio">No</div>
        </div>
      </div>
    `)
    const field = only()
    expect(field.context_label).toBe('Are you willing to relocate?')
    expect(field.options).toEqual(['Yes, anywhere', 'Only within Europe', 'No'])
  })

  it('finds a listbox dropdown', () => {
    page(`
      <div role="listitem">
        <div id="q" role="heading">Years of experience</div>
        <div role="listbox" aria-labelledby="q">
          <div role="option" data-value="0-2"></div>
          <div role="option" data-value="3-5"></div>
        </div>
      </div>
    `)
    const field = only()
    expect(field.type).toBe('select')
    expect(field.options).toEqual(['0-2', '3-5'])
  })

  it('reports which option is already chosen', () => {
    page(`
      <div role="listitem">
        <div id="q" role="heading">Preferred location</div>
        <div role="radiogroup" aria-labelledby="q">
          <div role="radio" aria-label="London" aria-checked="true"></div>
          <div role="radio" aria-label="Berlin" aria-checked="false"></div>
        </div>
      </div>
    `)
    expect(only().current_value).toBe('London')
  })
})

describe('Microsoft Forms', () => {
  it('reads a question out of its automation-id container', () => {
    page(`
      <div data-automation-id="questionContent">
        <div data-automation-id="questionTitle">Why do you want this job?</div>
        <textarea data-automation-id="textInput"></textarea>
      </div>
    `)
    expect(only().context_label).toBe('Why do you want this job?')
  })

  it('finds a checkbox built from a div', () => {
    page(`
      <div data-automation-id="questionContent">
        <div data-automation-id="questionTitle">I have a valid work permit</div>
        <div role="checkbox" aria-checked="false"></div>
      </div>
    `)
    const field = only()
    expect(field.type).toBe('checkbox')
    expect(field.context_label).toBe('I have a valid work permit')
  })
})

describe('shadow DOM', () => {
  it('finds an input inside an open shadow root', () => {
    page(`<div id="host"></div>`)
    shadow('#host', `<label for="a">Cover letter</label><textarea id="a"></textarea>`)
    const field = only()
    expect(field.context_label).toBe('Cover letter')
    expect(field.type).toBe('textarea')
  })

  it('resolves a label that lives in the same shadow root', () => {
    // The reason `document.querySelector` is never used for id lookups: the label
    // and the input are both inside the shadow root, and from `document` neither
    // exists. A document-scoped lookup finds nothing and reports no failure.
    page(`<div id="host"></div>`)
    shadow('#host', `<label for="x">Expected salary</label><input id="x" />`)
    expect(only().label_via).toBe('label_for')
  })

  it('groups radios inside a shadow root without reaching outside it', () => {
    page(`<div id="host"></div>`)
    shadow(
      '#host',
      `<fieldset>
         <legend>Do you require visa sponsorship?</legend>
         <label for="y">Yes</label><input type="radio" id="y" name="s" />
         <label for="n">No</label><input type="radio" id="n" name="s" />
       </fieldset>`
    )
    const field = only()
    expect(field.context_label).toBe('Do you require visa sponsorship?')
    expect(field.options).toEqual(['Yes', 'No'])
  })
})

describe('custom widgets', () => {
  it('treats a contenteditable div as a long answer', () => {
    page(`
      <div class="field">
        <label>Tell us about yourself</label>
        <div contenteditable="true"></div>
      </div>
    `)
    const field = only()
    expect(field.type).toBe('textarea')
    expect(field.context_label).toBe('Tell us about yourself')
  })

  it('asks a searchable dropdown once, not once for its own menu', () => {
    // react-select and friends: a combobox wrapper, a real <input> to type into,
    // and a listbox it points at. All three are candidates. Emitting all three
    // asks the same question three times; emitting only the wrapper gives a
    // question that cannot be typed into.
    page(`
      <div class="field">
        <label>Country of residence</label>
        <div role="combobox" aria-controls="lb"><input type="text" /></div>
        <div id="lb" role="listbox">
          <div role="option">India</div>
          <div role="option">Germany</div>
        </div>
      </div>
    `)
    const { fields } = scan()
    expect(fields).toHaveLength(1)
    expect(fields[0].type).toBe('select')
    expect(fields[0].options).toEqual(['India', 'Germany'])
  })

  it('keeps the typable input as the target, not the wrapper div', () => {
    page(`
      <div class="field">
        <label>Country of residence</label>
        <div role="combobox" aria-controls="lb"><input type="text" id="typeable" /></div>
        <div id="lb" role="listbox"><div role="option">India</div></div>
      </div>
    `)
    // Highlighting proves which element got registered: the wrapper has no value
    // to type into, so registering it would make the field permanently unfillable.
    expect(window.JobSyncFields.highlight(only().id)).toBe(true)
  })

  it('skips an aria-disabled control the way it skips a disabled input', () => {
    page(`
      <div class="field"><label>Editable</label><input /></div>
      <div class="field"><label>Locked</label><div role="textbox" aria-disabled="true"></div></div>
    `)
    expect(scan().fields.map((f) => f.context_label)).toEqual(['Editable'])
  })

  it('skips an aria-hidden control', () => {
    page(`
      <div class="field"><label>Real question</label><input /></div>
      <div class="field"><label>Decorative</label><div role="textbox" aria-hidden="true"></div></div>
    `)
    expect(scan().fields.map((f) => f.context_label)).toEqual(['Real question'])
  })

  it('reads aria-required on a div the way it reads required on an input', () => {
    page(`
      <div class="field">
        <label>Notice period</label>
        <div role="textbox" aria-required="true"></div>
      </div>
    `)
    expect(only().constraints.is_required).toBe(true)
  })
})
