import { useMemo, useRef, useState } from 'react'
import { api } from './api'
import { useSave } from './fields'
import type { ConfirmView, DocumentView, StructureView } from './types.generated'

/** Step one: get your history in.
 *
 * Two things happen here and the screen keeps them apart, because they have very
 * different consequences. Reading a document writes nothing — it produces a
 * proposal, and until it is saved a form field that would have used it asks you
 * instead. Saving writes to your profile permanently.
 *
 * The rest of the design is one rule: a bullet the model could not find in your
 * document is marked, and the marking does not go away by being ignored. Approving
 * model prose unchanged is the single move that turns a plausible sentence into a
 * permanent fact about your career, and the server refuses it outright — so the
 * box is editable right there, because rewriting it in your own words is both the
 * fix and the honest outcome.
 */
export function UploadScreen({ onSaved }: { onSaved: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [pasted, setPasted] = useState('')
  const [doc, setDoc] = useState<DocumentView | null>(null)
  const [candidate, setCandidate] = useState<StructureView | null>(null)
  const [dropping, setDropping] = useState(false)

  const [edits, setEdits] = useState<Record<string, string>>({})
  const [dropped, setDropped] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<ConfirmView | null>(null)

  const ingest = useSave()
  const read = useSave()
  const commit = useSave()

  const reset = () => {
    setCandidate(null)
    setEdits({})
    setDropped(new Set())
    setResult(null)
  }

  const take = (fn: () => Promise<DocumentView>) =>
    ingest.save(async () => {
      reset()
      setDoc(await fn())
    })

  const blockers = doc?.warnings.filter((w) => w.blocking) ?? []

  const unverified = useMemo(() => {
    const m = new Map<string, string>()
    for (const w of candidate?.warnings ?? []) {
      if (w.code === 'quote_not_found' && w.record_id) m.set(w.record_id, w.message)
    }
    return m
  }, [candidate])

  const allIds = useMemo(() => {
    const l = candidate?.ledger
    if (!l) return [] as string[]
    return [...l.employment, ...l.education, ...l.projects, ...l.credentials].map((r) => r.id)
  }, [candidate])

  const keeping = allIds.filter((id) => !dropped.has(id))

  const toggle = (id: string) => {
    const next = new Set(dropped)
    next.has(id) ? next.delete(id) : next.add(id)
    setDropped(next)
  }

  const save = () =>
    commit.save(async () => {
      if (!candidate) return
      setResult(
        await api.confirm({
          doc_id: candidate.doc_id,
          result: withEdits(candidate, edits),
          accept_record_ids: keeping,
          // Contact details and skills are what the document itself said, so they
          // come along; anything wrong is a two-second fix on the next screen.
          accept_profile_paths: candidate.profile
            ? ['email', 'phone_e164', 'location', 'links'].filter(
                (p) => contactValue(candidate, p) !== null
              )
            : [],
          accept_skills: candidate.skills,
          confirm_identity: Boolean(candidate.identity),
          unlock_identity: false,
          supersedes: {},
        })
      )
      onSaved()
    })

  return (
    <>
      <section>
        <h2>Add your history</h2>
        <div
          className={`drop${dropping ? ' over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDropping(true)
          }}
          onDragLeave={() => setDropping(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDropping(false)
            const f = e.dataTransfer.files?.[0]
            if (f) take(() => api.upload(f))
          }}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) take(() => api.upload(f))
            }}
          />
          <strong>{ingest.busy ? 'reading the file…' : 'Drop your résumé here'}</strong>
          <div className="hint">PDF, Word or plain text. Or click to pick a file.</div>
        </div>

        <details className="or">
          <summary>Paste it as text instead</summary>
          <textarea
            rows={6}
            value={pasted}
            placeholder="Paste your résumé here. Always works — no layout to get in the way."
            onChange={(e) => setPasted(e.target.value)}
          />
          <button
            className="btn sm"
            disabled={ingest.busy || !pasted.trim()}
            onClick={() => take(() => api.paste(pasted))}
          >
            Use this text
          </button>
        </details>
        {ingest.error && <div className="err">{ingest.error}</div>}
      </section>

      {doc && (
        <section>
          <h2>What we got out of it</h2>
          <div className="rec">
            <div className="sub2">
              {doc.filename ?? 'pasted text'} · {doc.word_count.toLocaleString()} words
              {doc.page_count ? ` · ${doc.page_count} page${doc.page_count === 1 ? '' : 's'}` : ''}
            </div>

            {blockers.length > 0 ? (
              <div className="hint warn">
                {blockers.map((w) => w.message).join(' ')} Paste the text instead — it always works.
              </div>
            ) : doc.layout === 'multi_column' ? (
              <div className="hint warn">
                This looks like a two-column layout, and those sometimes come out with lines
                interleaved. Have a quick look at the text below before saving anything — a scrambled
                line turns into a tidy job record with the wrong dates on it, and that is invisible
                two steps later.
              </div>
            ) : null}

            <details className="raw">
              <summary>See the raw text</summary>
              <pre>{doc.text || '(nothing was extracted)'}</pre>
            </details>

            <div className="savebar">
              <button
                className="btn"
                disabled={read.busy || !doc.is_usable}
                onClick={() =>
                  read.save(async () => {
                    reset()
                    setCandidate(await api.structure(doc.doc_id))
                  })
                }
              >
                {read.busy ? 'reading…' : candidate ? 'Read it again' : 'Read it'}
              </button>
              <span className="hint">
                This does not save anything. It reads the document into records you can check.
              </span>
            </div>
            {read.error && <div className="err">{read.error}</div>}
          </div>
        </section>
      )}

      {candidate && !result && (
        <section>
          <h2>
            Check it over <span className="count">{keeping.length}</span>
          </h2>
          <p className="lead">
            Untick anything that is not yours. Nothing here is saved yet.
          </p>

          {candidate.identity && (
            <div className="rec">
              <h4>
                {[
                  candidate.identity.legal_first,
                  candidate.identity.legal_middle,
                  candidate.identity.legal_last,
                ]
                  .filter(Boolean)
                  .join(' ')}
              </h4>
              <div className="hint">
                Saving locks your legal name. Changing it later takes a deliberate step — names do
                change, but not by accident.
              </div>
            </div>
          )}

          {candidate.ledger.employment.map((job) => (
            <div className={`rec${dropped.has(job.id) ? ' off' : ''}`} key={job.id}>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!dropped.has(job.id)}
                  onChange={() => toggle(job.id)}
                />
                <span>
                  <h4>
                    {job.title} · {job.employer}
                  </h4>
                  <div className="sub2">
                    {job.dates.start ?? '?'} → {job.dates.end ?? 'now'}
                    {job.location ? ` · ${job.location}` : ''}
                  </div>
                </span>
              </label>

              {job.achievements.map((ach) => {
                const warning = unverified.get(ach.id)
                const value = edits[ach.id] ?? ach.text
                const rewritten = warning !== undefined && value.trim() !== ach.text.trim()
                return (
                  <div className="bullet" key={ach.id}>
                    <textarea
                      rows={2}
                      value={value}
                      className={warning && !rewritten ? 'bad' : undefined}
                      onChange={(e) => setEdits({ ...edits, [ach.id]: e.target.value })}
                    />
                    {warning && !rewritten && (
                      <div className="hint warn">
                        This sentence is not in your document — the model wrote it. Saving it as it
                        stands is refused. Put it in your own words and it becomes yours, or clear it
                        and it goes away.
                      </div>
                    )}
                    {rewritten && <div className="hint ok">Your words now.</div>}
                  </div>
                )
              })}
            </div>
          ))}

          {[
            ...candidate.ledger.education.map((e) => ({
              id: e.id,
              title: `${e.degree}${e.field_of_study ? `, ${e.field_of_study}` : ''}`,
              sub: `${e.institution} · ${e.dates.end ?? 'in progress'}`,
            })),
            ...candidate.ledger.projects.map((p) => ({
              id: p.id,
              title: p.name,
              sub: p.summary ?? (p.employer_id ? 'built at work' : 'your own'),
            })),
            ...candidate.ledger.credentials.map((c) => ({
              id: c.id,
              title: c.name,
              sub: `${c.issuer}${c.issued ? ` · ${c.issued}` : ''}`,
            })),
          ].map((row) => (
            <label className={`rec check${dropped.has(row.id) ? ' off' : ''}`} key={row.id}>
              <input type="checkbox" checked={!dropped.has(row.id)} onChange={() => toggle(row.id)} />
              <span>
                <h4>{row.title}</h4>
                <div className="sub2">{row.sub}</div>
              </span>
            </label>
          ))}

          {candidate.skills.length > 0 && (
            <div className="rec">
              <h4>Skills it listed</h4>
              <div className="chips">
                {candidate.skills.map((s) => (
                  <span className="chip flat" key={s}>
                    {s}
                  </span>
                ))}
              </div>
              <div className="hint">
                Hard skills only. A résumé claiming "communication" is not evidence of it — that one
                only counts when something you did shows it, and you can add or remove any of these
                on the next screen.
              </div>
            </div>
          )}

          <div className="savebar sticky">
            <button className="btn" onClick={save} disabled={commit.busy || keeping.length === 0}>
              {commit.busy ? 'saving…' : `Save ${keeping.length} to my profile`}
            </button>
            <span className="hint">Anything unticked is thrown away, not kept for later.</span>
          </div>
          {commit.error && <div className="err">{commit.error}</div>}
        </section>
      )}

      {result && (
        <section>
          <h2>Saved</h2>
          <div className="rec">
            <p className="lead">
              {result.records_committed} record{result.records_committed === 1 ? '' : 's'} and{' '}
              {result.achievements_committed} bullet
              {result.achievements_committed === 1 ? '' : 's'} are in your profile.
              {result.achievements_user_authored > 0
                ? ` ${result.achievements_user_authored} of them in your own words.`
                : ''}
            </p>
            {result.rejections.length > 0 && (
              <div className="hint warn">
                {result.rejections.length} thing
                {result.rejections.length === 1 ? ' was' : 's were'} refused:
                <ul>
                  {result.rejections.map((r, i) => (
                    <li key={i}>{r.reason}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.skipped_existing.length > 0 && (
              <div className="hint">
                {result.skipped_existing.length} were already there, so nothing was duplicated.
              </div>
            )}
            <div className="savebar">
              <button className="btn ghost sm" onClick={() => reset()}>
                Add something else
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  )
}

/** Whether the document actually gave us that contact field, so an empty one is not
 * sent as a confirmation of nothing. */
function contactValue(c: StructureView, path: string): string | null {
  const p = c.profile
  if (!p) return null
  if (path === 'email') return p.email
  if (path === 'phone_e164') return p.phone_e164
  if (path === 'location') return p.location.city || p.location.region || p.location.country || null
  if (path === 'links') return p.links.linkedin || p.links.github || p.links.portfolio || null
  return null
}

/** Apply the rewritten bullets without touching what the model originally said, so
 * the marking on screen stays accurate while the user is still typing. */
function withEdits(candidate: StructureView, edits: Record<string, string>): StructureView {
  if (Object.keys(edits).length === 0) return candidate
  return {
    ...candidate,
    ledger: {
      ...candidate.ledger,
      employment: candidate.ledger.employment.map((job) => ({
        ...job,
        achievements: job.achievements
          .map((a) => (edits[a.id] === undefined ? a : { ...a, text: edits[a.id] }))
          // A bullet cleared to nothing is a bullet the user threw away.
          .filter((a) => a.text.trim().length > 0),
      })),
    },
  }
}
