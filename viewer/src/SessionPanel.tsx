import { useState } from 'react'

import type { ApplicationSession } from './types.generated'

/** L6 readout — the multi-page state a single-field call cannot have. */
export function SessionPanel({
  session,
  onNextPage,
  onEnd,
  onSetJd,
}: {
  session: ApplicationSession | null
  onNextPage: () => void
  onEnd: () => void
  onSetJd: (text: string) => Promise<{ replaced: boolean; stale_answers: number }>
}) {
  if (!session)
    return (
      <div className="empty">
        No application open. Start one above to see the JD retained across pages, evidence marked
        spent, and the back button replay answers instead of regenerating them.
      </div>
    )

  const spent = Object.entries(session.spent_chunks).sort((a, b) => b[1] - a[1])
  const generated = session.answered.filter((a) => !a.abstained)
  const abstained = session.answered.filter((a) => a.abstained)

  return (
    <div className="mem">
      <div className="card">
        <h3>Session</h3>
        <dl className="kv">
          <dt>id</dt>
          <dd>{session.session_id}</dd>
          <dt>page</dt>
          <dd>{session.page_index}</dd>
          <dt>mode</dt>
          <dd>{session.mode}</dd>
          <dt>JD</dt>
          <dd>
            {session.jd_fingerprint ? (
              <span>{session.jd_fingerprint} — retained</span>
            ) : (
              <span className="warnlist">none set</span>
            )}
          </dd>
          <dt>role</dt>
          <dd>{session.role_title || session.company || '—'}</dd>
          <dt>fields</dt>
          <dd>
            {generated.length} answered · {abstained.length} abstained
          </dd>
          <dt>stretches</dt>
          <dd>{session.stretches.length}</dd>
        </dl>
        <div className="actions" style={{ marginTop: 14 }}>
          <button className="btn ghost" onClick={onNextPage}>
            Next page →
          </button>
          <button className="btn ghost" onClick={onEnd}>
            End application
          </button>
        </div>
      </div>

      <JdCard session={session} onSetJd={onSetJd} />

      <div className="card">
        <h3>Spent evidence (anti-repetition ledger)</h3>
        {spent.length === 0 ? (
          <div className="empty">Nothing used yet.</div>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>chunk</th>
                <th>times used</th>
                <th>next-use multiplier</th>
              </tr>
            </thead>
            <tbody>
              {spent.map(([cid, n]) => (
                <tr key={cid}>
                  <td className="n">{cid}</td>
                  <td className="n">{n}</td>
                  <td className="n">
                    {n >= 2 ? (
                      <span className="pill gap">dropped</span>
                    ) : (
                      <span className="pill thin">×{(0.55 ** n).toFixed(2)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card wide">
        <h3>Answered this application (replayed on the back button)</h3>
        {session.answered.length === 0 ? (
          <div className="empty">Nothing answered yet.</div>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>page</th>
                <th>question</th>
                <th>answer</th>
                <th>evidence used</th>
              </tr>
            </thead>
            <tbody>
              {session.answered.map((a) => (
                <tr key={a.field_key}>
                  <td className="n">{a.page_index}</td>
                  <td>{a.question}</td>
                  <td className={a.abstained ? 'warnlist' : ''}>
                    {a.abstained ? 'abstained' : a.answer}
                  </td>
                  <td className="n">{a.used_chunks.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {session.stretches.length > 0 && (
        <div className="card wide">
          <h3>Claims made — the resume and cover letter must carry these too</h3>
          {session.stretches.map((s, i) => (
            <div className="stretchrow" key={i}>
              ↗ {s.claim} <span className="n">[{s.distance.toFixed(2)}]</span>
              <div className="note">{s.note}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** The job description, and a way to attach one after the fact.
 *
 * A session almost always exists before its JD does: the extension opens one on
 * the first question it answers, and on a Workday wizard the posting is out of
 * the DOM by page 4. Without somewhere to paste it, every answer for that
 * application is written for the role in general rather than for this posting.
 *
 * Replacing is allowed and reported. The answers already given were written
 * against the old description and this does not revise them — saying nothing
 * would leave you believing the whole application was tailored to a posting most
 * of it never saw.
 */
function JdCard({
  session,
  onSetJd,
}: {
  session: ApplicationSession
  onSetJd: (text: string) => Promise<{ replaced: boolean; stale_answers: number }>
}) {
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    setNote(null)
    try {
      const res = await onSetJd(draft)
      setDraft('')
      setNote(
        res.replaced
          ? `Replaced. ${res.stale_answers} answer${res.stale_answers === 1 ? '' : 's'} on this application were written against the previous description and have not been revised.`
          : 'Attached.'
      )
    } catch (e) {
      setNote(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card wide">
      <h3>Job description</h3>
      {session.jd_text ? (
        <pre className="jd">{session.jd_text}</pre>
      ) : (
        <div className="warnlist">
          None on file. Answers are being written for the role in general, not for this posting.
        </div>
      )}
      <textarea
        rows={5}
        value={draft}
        placeholder="Paste the posting to attach or replace it…"
        onChange={(e) => setDraft(e.target.value)}
        style={{ marginTop: 10 }}
      />
      <div className="actions" style={{ marginTop: 8 }}>
        <button className="btn ghost" onClick={save} disabled={busy || draft.trim().length < 40}>
          {session.jd_text ? 'Replace JD' : 'Attach JD'}
        </button>
        {/* The floor is the server's: under 40 characters is a cookie banner, not
            a job description, and a wrong JD steers every answer silently. */}
        <span className="n">{draft.trim().length} characters</span>
      </div>
      {note && <div className="note" style={{ marginTop: 8 }}>{note}</div>}
    </div>
  )
}
