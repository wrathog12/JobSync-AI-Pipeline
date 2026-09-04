/* Loading the content scripts the way Chrome does, and papering over the one
 * thing jsdom cannot do.
 *
 * `labels.js` and `fields.js` are classic scripts that hang their exports off
 * `window` — that is not a style choice, it is how two files injected by
 * `chrome.scripting.executeScript` share a scope without a bundler. So they are
 * evaluated rather than imported, which is also closer to what actually happens
 * on a real page.
 *
 * **jsdom does no layout.** Every element reports a zero-sized rect and a null
 * `offsetParent`, so the real `isVisible` would reject the entire page. Rather
 * than loosen a check that exists to keep us out of the hidden later pages of a
 * multi-step form, the harness supplies the layout jsdom is missing: an element
 * is "laid out" unless it or an ancestor is `display: none`, which is the rule
 * `offsetParent` encodes in a browser.
 */

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')

function fakeLayout() {
  Object.defineProperty(window.HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() {
      for (let el = this; el; el = el.parentElement) {
        if (el.style?.display === 'none' || el.hidden) return null
      }
      return this.parentElement
    },
  })
  window.Element.prototype.getBoundingClientRect = function () {
    const hidden = this.offsetParent === null
    return {
      width: hidden ? 0 : 120,
      height: hidden ? 0 : 24,
      top: 0,
      left: 0,
      right: 120,
      bottom: 24,
    }
  }
}

let loaded = false

/** Load the scripts once, then set the page. Returns nothing; use `window.JobSync*`. */
export function page(html) {
  if (!loaded) {
    fakeLayout()
    for (const file of ['labels.js', 'fields.js']) {
      // Indirect eval, so the script runs in global scope exactly as an injected
      // classic script does.
      // eslint-disable-next-line no-eval
      eval.call(null, readFileSync(join(SRC, file), 'utf8'))
    }
    loaded = true
  }
  document.body.innerHTML = html
}

export const scan = () => window.JobSyncFields.scan()
export const fill = (...args) => window.JobSyncFields.fill(...args)
export const resolve = (selector) =>
  window.JobSyncLabels.resolve(document.querySelector(selector))
/** The one field on a single-field page. Fails loudly rather than returning
 * undefined, since "the label came back wrong" and "nothing was found at all"
 * are different bugs and an undefined would report them identically. */
export function only() {
  const { fields } = scan()
  if (fields.length !== 1) throw new Error(`expected 1 field, found ${fields.length}`)
  return fields[0]
}
