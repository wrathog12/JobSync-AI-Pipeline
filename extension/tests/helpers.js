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

/** Up one level, crossing a shadow boundary. The top element of a shadow root
 * has no `parentElement` — its parent is the ShadowRoot — so a plain walk stops
 * dead there and reports everything inside a shadow root as invisible. */
const up = (node) => node.parentElement || node.parentNode?.host || null

function fakeLayout() {
  Object.defineProperty(window.HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() {
      // A detached node has no offset parent in a real browser either, and the
      // scan relies on that to notice the page changed under it.
      if (!this.isConnected) return null
      for (let el = this; el; el = up(el)) {
        if (el.style?.display === 'none' || el.hidden) return null
      }
      return up(this) || document.body
    },
  })
  // jsdom has no scrolling at all, so this does not exist to be called.
  window.Element.prototype.scrollIntoView = function () {}
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
    for (const file of ['labels.js', 'fields.js', 'jd.js']) {
      // Indirect eval, so the script runs in global scope exactly as an injected
      // classic script does.
      // eslint-disable-next-line no-eval
      eval.call(null, readFileSync(join(SRC, file), 'utf8'))
    }
    loaded = true
  }
  document.body.innerHTML = html
}

/** Attach an open shadow root to `selector` and fill it. Real ATS design systems
 * put their inputs in one, so a scan that cannot see inside finds nothing. */
export function shadow(selector, html) {
  const host = document.querySelector(selector)
  const root = host.attachShadow({ mode: 'open' })
  root.innerHTML = html
  return root
}

export const scan = () => window.JobSyncFields.scan()
export const readJd = () => window.JobSyncJD.read()
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
