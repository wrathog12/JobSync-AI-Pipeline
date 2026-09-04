/* The label cascade, against the markup real ATS platforms actually emit.
 *
 * `context_label` is the entire interface to the backend — it has no idea what a
 * DOM is. Every one of these fixtures is a shape that returns a useless label
 * under a naive `label[for]` lookup, and a useless label routes a real question
 * to ATTESTATION and abstains. So this file is the extension's equivalent of the
 * classifier tests: not polish, the load-bearing part.
 */

import { describe, expect, it } from 'vitest'
import { only, page, resolve } from './helpers.js'

describe('the label cascade', () => {
  it('reads a Greenhouse label whose id is full of selector syntax', () => {
    // Greenhouse ids look like `job_application_answers_attributes_0_text_value`
    // and on some forms contain brackets, which are CSS selector syntax. Putting
    // one inside `label[for="…"]` throws, and a throw here is invisible: the
    // cascade just falls through and labels the field from `name`.
    page(`
      <label for="job_application[answers][0][text]">Why do you want to work here?</label>
      <textarea id="job_application[answers][0][text]"></textarea>
    `)
    expect(resolve('textarea')).toEqual({
      label: 'Why do you want to work here?',
      via: 'label_for',
    })
  })

  it('reads a Lever label that wraps its input instead of pointing at it', () => {
    page(`
      <label class="application-label">
        <span>Tell us about a time you shipped something under pressure.</span>
        <textarea></textarea>
      </label>
    `)
    const { label, via } = resolve('textarea')
    expect(via).toBe('label_ancestor')
    expect(label).toBe('Tell us about a time you shipped something under pressure.')
  })

  it('follows aria-labelledby to a heading that is not a label at all', () => {
    page(`
      <h3 id="q4">Describe your experience with Kubernetes.</h3>
      <div><textarea aria-labelledby="q4"></textarea></div>
    `)
    expect(resolve('textarea')).toEqual({
      label: 'Describe your experience with Kubernetes.',
      via: 'aria_labelledby',
    })
  })

  it('reads a Workday container that labels without a `for`', () => {
    page(`
      <div data-automation-id="formField-workAuthorization">
        <label>Are you legally authorized to work in the United States?</label>
        <input type="text" />
      </div>
    `)
    const { label, via } = resolve('input')
    expect(via).toBe('question_container')
    expect(label).toBe('Are you legally authorized to work in the United States?')
  })

  it('falls back to whatever text sits above a bare React input', () => {
    page(`
      <div class="wrapper">
        <div class="prompt">What is your expected salary?</div>
        <div class="control"><input type="text" /></div>
      </div>
    `)
    const { label, via } = resolve('input')
    expect(via).toBe('preceding_text')
    expect(label).toBe('What is your expected salary?')
  })

  it('uses a placeholder only when nothing better exists', () => {
    page(`<input type="text" placeholder="Your portfolio URL" />`)
    expect(resolve('input')).toEqual({ label: 'Your portfolio URL', via: 'attribute' })
  })

  it('prefers a real label over a placeholder holding an example answer', () => {
    // The reason placeholder sits near the end of the cascade: "e.g. 5" is an
    // example, and sending it as the question makes the classifier look for a
    // field about the number five.
    page(`
      <label for="yrs">Years of professional experience</label>
      <input id="yrs" placeholder="e.g. 5" />
    `)
    expect(resolve('input').label).toBe('Years of professional experience')
  })

  it('de-camelises a name attribute as the last resort', () => {
    // Worse than a real label, better than nothing: the deny-list matches on
    // text, and it would rather see a rough label than an empty string. Failing
    // to catch a real sponsorship question because we sent "" is the outcome
    // this fallback exists to prevent.
    page(`<input type="text" name="workAuthorizationStatus_2" />`)
    expect(resolve('input')).toEqual({ label: 'work Authorization Status', via: 'attribute' })
  })

  it('strips the decoration ATS platforms put on required fields', () => {
    page(`
      <label for="e">Email address * (required):</label>
      <input id="e" type="email" required />
    `)
    expect(resolve('input').label).toBe('Email address')
  })

  it('does not swallow a select’s options into its label', () => {
    // The bug this catches is specific and silent: a wrapping <label> contains
    // the <select>, so textContent is the question plus every country on earth.
    // The backend then gets a 2,000-character "question".
    const countries = ['Select…', 'Afghanistan', 'Albania', 'Algeria', 'Zimbabwe']
    page(`
      <label>
        Country of residence
        <select>${countries.map((c) => `<option>${c}</option>`).join('')}</select>
      </label>
    `)
    const field = only()
    expect(field.context_label).toBe('Country of residence')
    expect(field.options).toEqual(countries)
  })

  it('reports which source produced the label', () => {
    // Surfaced all the way to the popup. When a field is read wrong, "which of
    // seven strategies produced this" is the first useful question, and guessing
    // it from the label alone is close to impossible.
    page(`<input aria-label="LinkedIn profile" />`)
    expect(resolve('input').via).toBe('aria_label')
  })

  it('gives up rather than inventing a label', () => {
    page(`<div><input type="text" /></div>`)
    expect(resolve('input')).toEqual({ label: '', via: 'none' })
    expect(scanCount()).toBe(0)
  })
})

function scanCount() {
  return window.JobSyncFields.scan().fields.length
}
