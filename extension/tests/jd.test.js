/* Reading the job description off a page.
 *
 * The tests that matter are the ones about *not* returning something: a page with
 * no description on it must say so, and a page whose description is buried in
 * navigation must not come back as the navigation. A JD that is really the site's
 * cookie banner is worse than no JD at all — it silently steers every answer in
 * the application, and nothing on screen looks wrong.
 */

import { describe, expect, it } from 'vitest'
import { page, readJd } from './helpers.js'

const DUTIES = `
  <p>You will own the ingestion pipeline end to end, from parsing uploaded
     documents to the retrieval layer that answers questions about them.</p>
  <ul>
    <li>Five years of Python, including at least one production service.</li>
    <li>Experience with retrieval systems, embeddings and evaluation sets.</li>
    <li>Comfortable owning a feature from design through to on-call.</li>
  </ul>
  <p>We work in small teams and ship weekly. The role is hybrid, two days a week
     in the London office, and reports to the head of platform engineering.</p>
`

describe('JSON-LD', () => {
  it('reads the posting a job board published for search engines', () => {
    // The best source there is: the site promised this to Google, so it is the
    // description and not the page around it — and it names the role and company.
    const posting = {
      '@context': 'https://schema.org',
      '@type': 'JobPosting',
      title: 'Senior Backend Engineer',
      hiringOrganization: { '@type': 'Organization', name: 'Northwind Labs' },
      description: `<p>You will own the ingestion pipeline.</p><ul><li>Five years of Python.</li></ul>
        <p>${'We ship weekly and work in small teams. '.repeat(6)}</p>`,
    }
    page(`
      <script type="application/ld+json">${JSON.stringify(posting)}</script>
      <nav><a href="/">Home</a><a href="/jobs">Jobs</a></nav>
      <div>${DUTIES}</div>
    `)
    const jd = readJd()
    expect(jd.source).toBe('json-ld')
    expect(jd.role_title).toBe('Senior Backend Engineer')
    expect(jd.company).toBe('Northwind Labs')
    expect(jd.jd_text).toContain('ingestion pipeline')
    // The bullet list is the most useful part of a JD, so it has to survive as
    // lines rather than arriving as one run of words.
    expect(jd.jd_text).toMatch(/\n/)
  })

  it('finds the posting inside an @graph next to unrelated nodes', () => {
    page(`
      <script type="application/ld+json">${JSON.stringify({
        '@graph': [
          { '@type': 'BreadcrumbList', itemListElement: [] },
          {
            '@type': 'JobPosting',
            title: 'Data Engineer',
            description: `<p>${'Own the pipeline and the tests around it. '.repeat(8)}</p>`,
          },
        ],
      })}</script>
      <div>${DUTIES}</div>
    `)
    expect(readJd().source).toBe('json-ld')
  })

  it('ignores a malformed block instead of losing the page with it', () => {
    page(`
      <script type="application/ld+json">{ this is not json </script>
      <div data-automation-id="jobPostingDescription">${DUTIES}</div>
    `)
    expect(readJd().source).toBe('container')
  })
})

describe('known containers', () => {
  it("reads Workday's posting body", () => {
    page(`
      <nav><a href="/">Careers</a></nav>
      <div data-automation-id="jobPostingDescription">${DUTIES}</div>
    `)
    const jd = readJd()
    expect(jd.source).toBe('container')
    expect(jd.jd_text).toContain('retrieval systems')
    expect(jd.jd_text).not.toContain('Careers')
  })

  it('leaves out the parts of the page that are not the job', () => {
    page(`
      <div data-automation-id="jobPostingDescription">
        ${DUTIES}
        <form><button>Apply now</button><input placeholder="Email" /></form>
        <script>window.track('view')</script>
      </div>
    `)
    const jd = readJd()
    expect(jd.jd_text).not.toContain('Apply now')
    expect(jd.jd_text).not.toContain('track')
  })
})

describe('following the text', () => {
  it('finds the description on a page with no useful markup at all', () => {
    page(`
      <header><h1>Senior Backend Engineer</h1></header>
      <nav><a href="/a">Other jobs</a><a href="/b">Life here</a><a href="/c">Benefits</a></nav>
      <div class="wrap"><div class="body">${DUTIES}</div></div>
      <footer><a href="/privacy">Privacy</a></footer>
    `)
    const jd = readJd()
    expect(jd.source).toBe('density')
    expect(jd.jd_text).toContain('head of platform engineering')
    expect(jd.jd_text).not.toContain('Privacy')
  })

  it('takes the prose over a longer rail of links', () => {
    // "Similar jobs" lists are often longer than the description in raw character
    // count. Discounting link text is the whole reason this picks the right one.
    const rail = Array.from(
      { length: 40 },
      (_, i) => `<a href="/job/${i}">Senior Backend Engineer, team number ${i}</a>`
    ).join('')
    page(`
      <div class="rail">${rail}</div>
      <div class="post">${DUTIES}</div>
    `)
    expect(readJd().jd_text).toContain('ingestion pipeline')
  })
})

describe('when there is nothing to read', () => {
  it('says so rather than returning the page furniture', () => {
    page(`
      <nav><a href="/">Home</a></nav>
      <h1>Sign in to continue</h1>
      <p>Please log in to view this job.</p>
    `)
    const jd = readJd()
    expect(jd.jd_text).toBe('')
    expect(jd.source).toBe('none')
  })

  it('still reports a role and company guess, since those only label a session', () => {
    page(`<h1>Staff Engineer, Platform</h1><p>Log in to continue.</p>`)
    expect(readJd().role_title).toBe('Staff Engineer, Platform')
  })
})
