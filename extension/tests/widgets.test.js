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
import { fill, only, page, scan, shadow } from './helpers.js'

/** Make the div widgets in a fixture behave like the framework that built them.
 *
 * jsdom dispatches the click and then nothing happens, because the "radio" is a
 * div and the state lives in a React component that is not here. Without this the
 * fill tests would assert only that we dispatched an event, which is the half that
 * was never in doubt — what matters is that the read-back afterwards sees the
 * change, and that requires something to actually change. */
function reactive(selector = 'body') {
  const scope = document.querySelector(selector)
  for (const el of scope.querySelectorAll('[role="radio"]')) {
    el.addEventListener('click', () => {
      const group = el.closest('[role="radiogroup"]') || scope
      for (const other of group.querySelectorAll('[role="radio"]')) {
        other.setAttribute('aria-checked', String(other === el))
      }
    })
  }
  for (const el of scope.querySelectorAll('[role="checkbox"], [role="switch"]')) {
    el.addEventListener('click', () => {
      el.setAttribute('aria-checked', String(el.getAttribute('aria-checked') !== 'true'))
    })
  }
}

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

describe('multi-select', () => {
  const APPLY = `
    <div role="listitem">
      <div id="q" role="heading">Which of these have you worked with?</div>
      <div role="group" aria-labelledby="q">
        <div role="checkbox" aria-checked="false" aria-label="Python"></div>
        <div role="checkbox" aria-checked="false" aria-label="Rust"></div>
        <div role="checkbox" aria-checked="false" aria-label="Go"></div>
      </div>
    </div>
  `

  it('asks a group of checkboxes as one question, not one each', () => {
    // The bug this replaces: three questions called "Python", "Rust" and "Go",
    // each of which the backend is asked to answer. The question is the heading;
    // the box labels are the answers to it.
    page(APPLY)
    const field = only()
    expect(field.multi).toBe(true)
    expect(field.context_label).toBe('Which of these have you worked with?')
    expect(field.options).toEqual(['Python', 'Rust', 'Go'])
  })

  it('keeps a lone checkbox as its own yes/no question', () => {
    page(`
      <div role="listitem">
        <div role="heading">Consent</div>
        <div role="checkbox" aria-label="I agree to the privacy policy"></div>
      </div>
    `)
    expect(only().type).toBe('checkbox')
    expect(only().multi).toBe(false)
  })

  it('ticks every option the answer names', async () => {
    page(APPLY)
    reactive()
    const result = await fill(only().id, 'Python, Go', 'deterministic')
    expect(result.ok).toBe(true)
    expect(result.wrote).toBe('Python, Go')
    const state = [...document.querySelectorAll('[role="checkbox"]')].map((el) =>
      el.getAttribute('aria-checked')
    )
    expect(state).toEqual(['true', 'false', 'true'])
  })

  it('leaves the boxes the answer did not name alone rather than unticking them', async () => {
    // An already-ticked box may be a choice the user made by hand. Clearing it
    // because the generated answer forgot to mention it is worse than leaving one
    // box too many.
    page(APPLY)
    document.querySelectorAll('[role="checkbox"]')[1].setAttribute('aria-checked', 'true')
    reactive()
    await fill(only().id, 'Python', 'deterministic')
    expect(document.querySelectorAll('[role="checkbox"]')[1].getAttribute('aria-checked')).toBe(
      'true'
    )
  })

  it('names the parts of the answer that matched nothing', async () => {
    page(APPLY)
    reactive()
    const result = await fill(only().id, 'Python and Haskell', 'deterministic')
    expect(result.ok).toBe(true)
    expect(result.wrote).toBe('Python')
    expect(result.unmatched).toEqual(['Haskell'])
  })

  it('reports which boxes are already ticked', () => {
    page(APPLY)
    document.querySelectorAll('[role="checkbox"]')[0].setAttribute('aria-checked', 'true')
    document.querySelectorAll('[role="checkbox"]')[2].setAttribute('aria-checked', 'true')
    expect(only().current_value).toBe('Python, Go')
  })
})

describe('clicking a choice', () => {
  const TEAM = `
    <div role="listitem">
      <div id="q" role="heading">Which team are you applying to?</div>
      <div role="radiogroup" aria-labelledby="q">
        <div role="radio" aria-checked="false" aria-label="Engineering"></div>
        <div role="radio" aria-checked="false" aria-label="Design"></div>
      </div>
    </div>
  `

  it('picks a div radio and reads the choice back', async () => {
    page(TEAM)
    reactive()
    const result = await fill(only().id, 'Design', 'deterministic')
    expect(result).toEqual({ ok: true, wrote: 'Design' })
    expect(document.querySelectorAll('[role="radio"]')[1].getAttribute('aria-checked')).toBe('true')
  })

  it('matches an answer to an option that spells it out', async () => {
    page(`
      <div role="listitem">
        <div id="q" role="heading">Are you legally allowed to work in the UK?</div>
        <div role="radiogroup" aria-labelledby="q">
          <div role="radio" aria-checked="false" aria-label="Yes, I have the right to work"></div>
          <div role="radio" aria-checked="false" aria-label="No, I would need sponsorship"></div>
        </div>
      </div>
    `)
    reactive()
    const result = await fill(only().id, 'Yes', 'deterministic')
    expect(result.wrote).toBe('Yes, I have the right to work')
  })

  it('refuses to guess when the answer matches no option', async () => {
    // "No" is a substring of "Not sure", and picking that for an answer of No is
    // the kind of wrong that nobody catches: the user reads "filled" and submits.
    page(`
      <div role="listitem">
        <div id="q" role="heading">Preferred start date</div>
        <div role="radiogroup" aria-labelledby="q">
          <div role="radio" aria-checked="false" aria-label="Immediately"></div>
          <div role="radio" aria-checked="false" aria-label="In one month"></div>
        </div>
      </div>
    `)
    reactive()
    const result = await fill(only().id, 'Some time next year', 'deterministic')
    expect(result.ok).toBe(false)
    expect(result.reason).toMatch(/no option matching/)
    expect(document.querySelectorAll('[role="radio"]')[0].getAttribute('aria-checked')).toBe('false')
  })

  it('never clicks a radio the backend called an attestation', async () => {
    // The whole point of the deny-list, at the only place it can still be enforced.
    page(`
      <div role="listitem">
        <div id="q" role="heading">Do you require visa sponsorship?</div>
        <div role="radiogroup" aria-labelledby="q">
          <div role="radio" aria-checked="false" aria-label="Yes"></div>
          <div role="radio" aria-checked="false" aria-label="No"></div>
        </div>
      </div>
    `)
    reactive()
    const result = await fill(only().id, 'No', 'attestation')
    expect(result.ok).toBe(false)
    const state = [...document.querySelectorAll('[role="radio"]')].map((el) =>
      el.getAttribute('aria-checked')
    )
    expect(state).toEqual(['false', 'false'])
  })

  it('says the click did not register rather than claiming an answer', async () => {
    // No listener at all: the div is inert, so nothing changes. Reporting success
    // here would tell the user a required question is answered when it is blank.
    page(TEAM)
    const result = await fill(only().id, 'Design', 'deterministic')
    expect(result.ok).toBe(false)
    expect(result.reason).toMatch(/did not take it/)
  })

  it('opens a searchable dropdown, waits for the menu, and clicks a choice', async () => {
    page(`
      <div class="field">
        <label>Country of residence</label>
        <div role="combobox" aria-controls="lb"><input type="text" /></div>
        <div id="lb" role="listbox"></div>
      </div>
    `)
    const input = document.querySelector('input')
    const menu = document.querySelector('#lb')
    // react-select renders no options until it is opened, and then a tick later.
    input.addEventListener('click', () => {
      setTimeout(() => {
        menu.innerHTML = `<div role="option">India</div><div role="option">Germany</div>`
        for (const option of menu.querySelectorAll('[role="option"]')) {
          option.addEventListener('click', () => {
            input.value = option.textContent
            menu.innerHTML = ''
          })
        }
      }, 60)
    })

    const result = await fill(only().id, 'Germany', 'deterministic')
    expect(result).toEqual({ ok: true, wrote: 'Germany' })
    expect(input.value).toBe('Germany')
  })

  it('says so when the dropdown will not open', async () => {
    page(`
      <div class="field">
        <label>Country of residence</label>
        <div role="combobox" aria-controls="lb"><input type="text" /></div>
        <div id="lb" role="listbox"></div>
      </div>
    `)
    const result = await fill(only().id, 'Germany', 'deterministic')
    expect(result.ok).toBe(false)
    expect(result.reason).toMatch(/would not open/)
  })
})
