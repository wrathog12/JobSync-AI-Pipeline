/* Reading the job description off the page.
 *
 * Without this the whole product is guessing. "Why do you want this role?" cannot
 * be answered from memory alone, retrieval has nothing to aim at, and a résumé
 * tailored to no particular job is just a résumé. The backend has had a slot for
 * the JD since the beginning (`ApplicationSession.jd_text`, and `answer.py` mixes
 * it into the retrieval query) — nothing ever filled it.
 *
 * Three sources, best first, and each one is honest about which it was:
 *
 *   **JSON-LD.** The only place a job board *promises* the description in a
 *   machine-readable form. Google Jobs will not index a listing without
 *   `JobPosting` markup, so most boards emit it whether they meant to or not, and
 *   it carries the role title and company name as a bonus.
 *
 *   **Known containers.** Workday's `jobPostingDescription`, Greenhouse's
 *   `#content`, Lever's posting body. Reliable while they last, which is the
 *   problem with all selector lists.
 *
 *   **Text density.** Follow the prose: descend from `<body>` while a single child
 *   still holds most of the page's text, discounting link text because navigation
 *   and "similar jobs" rails are mostly links and a description is mostly
 *   sentences. Works on a page nobody has ever seen before, which is the point.
 *
 * The JD is then kept on the *session*, not re-read per page: by page 4 of a
 * Workday wizard the description is long gone from the DOM.
 */

if (!window.JobSyncJD) {
  /** Generous. A long JD is 1,000 words; this is roughly ten times that, and the
   * backend excerpts what it needs rather than sending the lot to a model. */
  const MAX = 20000

  const tidy = (s) =>
    (s || '')
      .replace(/ /g, ' ')
      .replace(/\r/g, '')
      .replace(/[ \t]+/g, ' ')
      .replace(/ *\n */g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim()

  /** Things that are on the page but are not the job description. */
  const NOISE =
    'script, style, noscript, svg, nav, footer, aside, form, button, select, textarea,' +
    'input, [role="navigation"], [aria-hidden="true"]'

  /** Elements that end a line. Without these the bullet list of requirements —
   * the most useful part of any JD — arrives as one unreadable run of words. */
  const BLOCK = 'p, li, br, h1, h2, h3, h4, h5, tr, div, section, article'

  function readable(el) {
    if (!el) return ''
    const copy = el.cloneNode(true)
    copy.querySelectorAll(NOISE).forEach((n) => n.remove())
    for (const node of copy.querySelectorAll(BLOCK)) {
      try {
        node.insertAdjacentText('beforebegin', '\n')
      } catch {
        /* no parent to insert into; the text is still there */
      }
    }
    return tidy(copy.textContent)
  }

  /** Parsed inert. `innerHTML` on a real element can still start an image load,
   * and this HTML came off someone else's page. */
  const parse = (html) => new DOMParser().parseFromString(html, 'text/html').body

  // ── source 1: JSON-LD ───────────────────────────────────────────────────────

  function* flatten(node) {
    if (Array.isArray(node)) {
      for (const item of node) yield* flatten(item)
      return
    }
    if (!node || typeof node !== 'object') return
    yield node
    if (node['@graph']) yield* flatten(node['@graph'])
  }

  function fromLinkedData() {
    for (const tag of document.querySelectorAll('script[type="application/ld+json"]')) {
      let data
      try {
        data = JSON.parse(tag.textContent)
      } catch {
        continue // one malformed block must not lose the others
      }
      for (const node of flatten(data)) {
        const types = [].concat(node['@type'] || []).join(' ')
        if (!/JobPosting/i.test(types)) continue
        const raw = typeof node.description === 'string' ? node.description : ''
        const text = /<[a-z][\s\S]*>/i.test(raw) ? readable(parse(raw)) : tidy(raw)
        if (text.length < 200) continue
        return {
          jd_text: text,
          role_title: tidy(node.title || ''),
          company: tidy(node.hiringOrganization?.name || ''),
          source: 'json-ld',
        }
      }
    }
    return null
  }

  // ── source 2: containers the big platforms use ──────────────────────────────

  const CONTAINERS = [
    '[data-automation-id="jobPostingDescription"]', // Workday
    '[data-qa="job-description"]', // Ashby and others
    '[class*="posting-description"]', // Lever
    '#jobDescriptionText', // Indeed
    '#job-description, .job-description, [class*="jobDescription"]',
    '[class*="job-description"]',
    '#content', // Greenhouse, inside its iframe
    'article, [role="article"]',
  ]

  function fromContainer() {
    for (const selector of CONTAINERS) {
      for (const el of document.querySelectorAll(selector)) {
        const text = readable(el)
        if (text.length >= 400) return { jd_text: text, source: 'container' }
      }
    }
    return null
  }

  // ── source 3: follow the text ───────────────────────────────────────────────

  const scoreOf = (el) => {
    const text = tidy(el.textContent).length
    const links = [...el.querySelectorAll('a')].reduce((n, a) => n + tidy(a.textContent).length, 0)
    return text - links * 3
  }

  function byDensity() {
    let node = document.body
    if (!node) return null
    for (let depth = 0; depth < 12; depth += 1) {
      let best = null
      for (const child of node.children) {
        if (child.matches(NOISE)) continue
        const value = scoreOf(child)
        if (!best || value > best.value) best = { el: child, value }
      }
      // Stop where the text splits across siblings: that container is the
      // description, and one level further down is a single paragraph of it.
      if (!best || best.value < scoreOf(node) * 0.85) break
      node = best.el
    }
    const text = readable(node)
    return text.length >= 400 ? { jd_text: text, source: 'density' } : null
  }

  // ── who and what ────────────────────────────────────────────────────────────

  const meta = (name) =>
    tidy(document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content || '')

  /** Role and company. Only ever labels on a session — nothing is answered from
   * these — so a rough guess beats leaving the session unnamed. */
  function titles() {
    const heading = tidy(document.querySelector('h1')?.textContent || '')
    return {
      role_title: heading || meta('og:title') || tidy(document.title),
      company: meta('og:site_name') || tidy(location.hostname.replace(/^www\./, '')),
    }
  }

  function read() {
    const found = fromLinkedData() || fromContainer() || byDensity()
    const guess = titles()
    if (!found) return { jd_text: '', source: 'none', url: location.href, ...guess }
    return {
      jd_text: found.jd_text.slice(0, MAX),
      truncated: found.jd_text.length > MAX,
      source: found.source,
      role_title: found.role_title || guess.role_title,
      company: found.company || guess.company,
      url: location.href,
    }
  }

  window.JobSyncJD = { read, readable, tidy }
}
