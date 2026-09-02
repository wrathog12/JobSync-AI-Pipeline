import { useMemo, useState } from 'react'
import { api } from './api'
import type {
  ConfirmView,
  DocumentView,
  Employment,
  StructureView,
} from './types.generated'

/** Steps 3 and 4 in one screen: what the model read, and what you agree to keep.
 *
 * The design decision this panel exists to make visible is that nothing here is
 * memory yet. Every checkbox is off by default — omission is not consent — and a
 * bullet the model could not find in your document is marked, because approving
 * that unchanged is the one move that quietly turns model prose into a permanent
 * fact about your career. Edit it and it becomes your own words instead, which is
 * exactly what the server checks for.
 */
export function ReviewPanel({
  doc,
  onCommitted,
}: {
  doc: DocumentView | null
  onCommitted: () => void
}) {
  const [candidate, setCandidate] = useState<StructureView | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [records, setRecords] = useState<Set<string>>(new Set())
  const [paths, setPaths] = useState<Set<string>>(new Set())
  const [skills, setSkills] = useState<Set<string>>(new Set())
  const [identity, setIdentity] = useState(false)
  const [unlock, setUnlock] = useState(false)
  const [result, setResult] = useState<ConfirmView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** Achievement id -> the warning against it, for the inline marker. */
  const flagged = useMemo(() => {
    const m = new Map<string, string>()
    for (const w of candidate?.warnings ?? []) {
      if (w.code === 'quote_not_found' && w.record_id) m.set(w.record_id, w.message)
    }
    return m
  }, [candidate])

  const allRecordIds = useMemo(() => {
    const led = candidate?.ledger
    if (!led) return [] as string[]
    return [...led.employment, ...led.education, ...led.projects, ...led.credentials].map(
      (r) => r.id,
    )
  }, [candidate])

  const reset = () => {
    setEdits({})
    setRecords(new Set())
    setPaths(new Set())
    setSkills(new Set())
    setIdentity(false)
    setUnlock(false)
    setResult(null)
  }

  const structure = async () => {
    if (!doc) return
    setBusy(true)
    setError(null)
    try {
      reset()
      setCandidate(await api.structure(doc.doc_id))
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    if (!candidate) return
    setBusy(true)
    setError(null)
    try {
      setResult(
        await api.confirm({
          doc_id: candidate.doc_id,
          // The edits are applied here rather than in place, so the panel can
          // always show what the model originally said next to what you changed.
          result: withEdits(candidate, edits),
          accept_record_ids: [...records],
          accept_profile_paths: [...paths],
          accept_skills: [...skills],
          confirm_identity: identity,
          unlock_identity: unlock,
          supersedes: {},
        }),
      )
      onCommitted()
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  const toggle = <T,>(set: Set<T>, apply: (s: Set<T>) => void, key: T) => {
    const next = new Set(set)
    next.has(key) ? next.delete(key) : next.add(key)
    apply(next)
  }

  if (!doc) {
    return (
      <div className="mem">
        <div className="card wide">
          <div className="empty">
            Nothing to review. Extract a document on the Ingest tab first — this step reads from
            there.
          </div>
        </div>
      </div>
    )
  }

  const nothingChosen =
    records.size === 0 && paths.size === 0 && skills.size === 0 && !identity

  return (
    <div className="mem">
      <div className="card wide">
        <h3>Read the document into candidate records</h3>
        <div className="src" style={{ marginBottom: 10 }}>
          One LLM call on <code>{doc.filename ?? doc.doc_id}</code>. Nothing is saved by this —
          everything below is a proposal at <strong>parsed_unconfirmed</strong>, and until you
          confirm it, a form field that would use it abstains instead.
        </div>
        <div className="actions" style={{ paddingTop: 0 }}>
          <button className="btn" onClick={structure} disabled={busy || !doc.is_usable}>
            {busy ? 'reading…' : candidate ? 'Read again' : 'Structure this document'}
          </button>
          {candidate && (
            <button
              className="btn ghost"
              onClick={() => setRecords(new Set(allRecordIds))}
              disabled={busy}
            >
              Select all {allRecordIds.length} records
            </button>
          )}
          {!doc.is_usable && (
            <span className="pill gap">document is blocked — paste the text instead</span>
          )}
        </div>
        {error && <div className="err">{error}</div>}
      </div>

      {candidate && (
        <div className="card">
          <h3>What the model returned</h3>
          <dl className="kv">
            <dt>model</dt>
            <dd>{candidate.model || '—'}</dd>
            <dt>records</dt>
            <dd>
              {candidate.record_count} · {candidate.achievement_count} bullets
            </dd>
            <dt>unverified</dt>
            <dd>
              {candidate.unverified_quotes === 0 ? (
                <span className="pill thin">every bullet found in your document</span>
              ) : (
                <span className="pill gap">
                  {candidate.unverified_quotes} bullet
                  {candidate.unverified_quotes === 1 ? '' : 's'} not in your document
                </span>
              )}
            </dd>
            <dt>tokens</dt>
            <dd>
              {candidate.prompt_tokens} in · {candidate.output_tokens} out
              {candidate.thinking_tokens ? ` · ${candidate.thinking_tokens} thinking` : ''}
            </dd>
            <dt>latency</dt>
            <dd>{candidate.ms} ms</dd>
          </dl>
        </div>
      )}

      {candidate && candidate.identity && (
        <div className="card">
          <h3>Identity (L0 — locks on confirm)</h3>
          <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <input type="checkbox" checked={identity} onChange={() => setIdentity(!identity)} />
            <span>
              <strong>
                {[
                  candidate.identity.legal_first,
                  candidate.identity.legal_middle,
                  candidate.identity.legal_last,
                ]
                  .filter(Boolean)
                  .join(' ')}
              </strong>
              <div className="note">
                Confirming locks this. Changing it later takes a deliberate unlock — names do
                change, but not by accident.
              </div>
            </span>
          </label>
          {identity && (
            <label style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <input type="checkbox" checked={unlock} onChange={() => setUnlock(!unlock)} />
              <span className="note">
                Overwrite an already-locked name (marriage, naturalization, a bad first parse).
              </span>
            </label>
          )}
        </div>
      )}

      {candidate && candidate.profile && (
        <div className="card">
          <h3>Contact (L1)</h3>
          {(
            [
              ['email', candidate.profile.email],
              ['phone_e164', candidate.profile.phone_e164],
              [
                'location',
                [candidate.profile.location.city, candidate.profile.location.region]
                  .filter(Boolean)
                  .join(', '),
              ],
              [
                'links',
                [candidate.profile.links.linkedin, candidate.profile.links.github]
                  .filter(Boolean)
                  .join('  '),
              ],
            ] as [string, string | null][]
          ).map(([path, value]) => (
            <label key={path} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
              <input
                type="checkbox"
                checked={paths.has(path)}
                disabled={!value}
                onChange={() => toggle(paths, setPaths, path)}
              />
              <span>
                <code>{path}</code> — {value || <span className="note">not found</span>}
              </span>
            </label>
          ))}
          <div className="note" style={{ marginTop: 10 }}>
            Work authorization and comp preferences are deliberately absent. A résumé does not
            state them, and a guess here is how someone ends up attesting to something untrue.
          </div>
        </div>
      )}

      {candidate?.ledger.employment.map((job) => (
        <EmploymentCard
          key={job.id}
          job={job}
          checked={records.has(job.id)}
          onToggle={() => toggle(records, setRecords, job.id)}
          edits={edits}
          onEdit={(id, text) => setEdits({ ...edits, [id]: text })}
          flagged={flagged}
        />
      ))}

      {candidate && candidate.ledger.education.length > 0 && (
        <div className="card">
          <h3>Education (L2)</h3>
          {candidate.ledger.education.map((ed) => (
            <label key={ed.id} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={records.has(ed.id)}
                onChange={() => toggle(records, setRecords, ed.id)}
              />
              <span>
                <strong>{ed.degree}</strong>
                {ed.field_of_study ? `, ${ed.field_of_study}` : ''} — {ed.institution}
                <div className="note">
                  {ed.dates.start ?? '?'} → {ed.dates.end ?? 'present'}
                  {ed.gpa != null ? ` · GPA ${ed.gpa}` : ' · GPA not stated'}
                </div>
              </span>
            </label>
          ))}
        </div>
      )}

      {candidate && candidate.ledger.projects.length > 0 && (
        <div className="card">
          <h3>Projects (L2)</h3>
          {candidate.ledger.projects.map((pr) => (
            <label key={pr.id} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={records.has(pr.id)}
                onChange={() => toggle(records, setRecords, pr.id)}
              />
              <span>
                <strong>{pr.name}</strong>
                <div className="note">
                  {pr.employer_id ? 'employer work' : 'personal'}
                  {pr.summary ? ` · ${pr.summary}` : ''}
                </div>
              </span>
            </label>
          ))}
        </div>
      )}

      {candidate && candidate.ledger.credentials.length > 0 && (
        <div className="card">
          <h3>Credentials (L2)</h3>
          {candidate.ledger.credentials.map((cr) => (
            <label key={cr.id} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={records.has(cr.id)}
                onChange={() => toggle(records, setRecords, cr.id)}
              />
              <span>
                <strong>{cr.name}</strong>
                <div className="note">
                  {cr.issuer}
                  {cr.issued ? ` · ${cr.issued}` : ''}
                </div>
              </span>
            </label>
          ))}
        </div>
      )}

      {candidate && candidate.skills.length > 0 && (
        <div className="card">
          <h3>Skills the document lists</h3>
          <div className="src" style={{ marginBottom: 8 }}>
            Hard skills only. A soft skill is refused even if your résumé claims it — it counts
            for something only when an achievement demonstrates it, and that version is the one
            worth showing an employer.
          </div>
          <div className="modes" style={{ flexWrap: 'wrap' }}>
            {candidate.skills.map((s) => (
              <button
                key={s}
                data-active={skills.has(s)}
                onClick={() => toggle(skills, setSkills, s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {candidate && candidate.warnings.length > 0 && (
        <div className="card wide">
          <h3>Warnings — {candidate.blocking.length} worth stopping for</h3>
          {candidate.warnings.map((w, i) => (
            <div className={candidate.blocking.includes(w) ? 'violation' : 'stretchrow'} key={i}>
              {candidate.blocking.includes(w) ? '✗ ' : '⚠ '}
              <strong>{w.code}</strong>
              <div className="note">{w.message}</div>
            </div>
          ))}
        </div>
      )}

      {candidate && (
        <div className="card wide">
          <h3>Commit</h3>
          <div className="src">
            {records.size} record{records.size === 1 ? '' : 's'} · {paths.size} contact field
            {paths.size === 1 ? '' : 's'} · {skills.size} skill{skills.size === 1 ? '' : 's'}
            {identity ? ' · identity' : ''}. Anything unchecked is discarded, not remembered for
            later.
          </div>
          <div className="actions" style={{ paddingTop: 10 }}>
            <button className="btn" onClick={submit} disabled={busy || nothingChosen}>
              {busy ? 'committing…' : 'Confirm and write to memory'}
            </button>
            <button className="btn ghost" onClick={reset} disabled={busy}>
              Clear selection
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="card wide">
          <h3>Committed</h3>
          <dl className="kv">
            <dt>records</dt>
            <dd>
              {result.records_committed} ({result.employment_committed} jobs,{' '}
              {result.education_committed} education, {result.projects_committed} projects,{' '}
              {result.credentials_committed} credentials)
            </dd>
            <dt>bullets</dt>
            <dd>
              {result.achievements_committed}
              {result.achievements_user_authored > 0
                ? ` · ${result.achievements_user_authored} in your own words`
                : ''}
            </dd>
            <dt>skills</dt>
            <dd>{result.skills_committed}</dd>
            <dt>contact</dt>
            <dd>{result.profile_paths_committed.join(', ') || '—'}</dd>
            <dt>identity</dt>
            <dd>
              {result.identity_committed ? 'committed and locked' : result.identity_locked ? 'already locked' : '—'}
            </dd>
            <dt>evidence</dt>
            <dd>{result.evidence_chunks} chunks — this is what retrieval can now reach</dd>
            {result.skipped_existing.length > 0 && (
              <>
                <dt>already had</dt>
                <dd>{result.skipped_existing.length} (re-confirming is a no-op, not a duplicate)</dd>
              </>
            )}
          </dl>
          {result.rejections.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {result.rejections.map((r, i) => (
                <div className="violation" key={i}>
                  ✗ <code>{r.record_id}</code>
                  <div className="note">{r.reason}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function EmploymentCard({
  job,
  checked,
  onToggle,
  edits,
  onEdit,
  flagged,
}: {
  job: Employment
  checked: boolean
  onToggle: () => void
  edits: Record<string, string>
  onEdit: (id: string, text: string) => void
  flagged: Map<string, string>
}) {
  return (
    <div className="card wide">
      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span>
          <h3 style={{ margin: 0 }}>
            {job.title} — {job.employer}
          </h3>
          <div className="note">
            {job.dates.start ?? '?'} → {job.dates.end ?? 'present'}
            {job.location ? ` · ${job.location}` : ''} · {job.employment_type}
          </div>
        </span>
      </label>

      <div style={{ marginTop: 12 }}>
        {job.achievements.map((ach) => {
          const warning = flagged.get(ach.id)
          const edited = edits[ach.id] !== undefined && edits[ach.id] !== ach.text
          return (
            <div key={ach.id} style={{ marginBottom: 12 }}>
              <textarea
                rows={2}
                value={edits[ach.id] ?? ach.text}
                onChange={(e) => onEdit(ach.id, e.target.value)}
                style={warning && !edited ? { borderColor: 'var(--bad, #b4453c)' } : undefined}
              />
              <div className="note">
                {warning ? (
                  edited ? (
                    <>✓ Your wording now, so it counts as evidence.</>
                  ) : (
                    <>✗ {warning}</>
                  )
                ) : edited ? (
                  <>edited — will be saved as your own words</>
                ) : (
                  <>
                    verbatim from your document
                    {ach.metrics.length > 0 ? ` · ${ach.metrics.join(', ')}` : ''}
                  </>
                )}
              </div>
            </div>
          )
        })}
        {job.achievements.length === 0 && (
          <div className="empty">
            No bullets were associated with this role. If your résumé has them, the layout probably
            broke — paste the text instead.
          </div>
        )}
      </div>
    </div>
  )
}

/** Apply the inline edits without mutating the candidate the panel is rendering. */
function withEdits(candidate: StructureView, edits: Record<string, string>): StructureView {
  if (Object.keys(edits).length === 0) return candidate
  return {
    ...candidate,
    ledger: {
      ...candidate.ledger,
      employment: candidate.ledger.employment.map((job) => ({
        ...job,
        achievements: job.achievements.map((a) =>
          edits[a.id] === undefined ? a : { ...a, text: edits[a.id] },
        ),
      })),
    },
  }
}
