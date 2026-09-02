import type { ApplicationSession } from './types.generated'

/** L6 readout — the multi-page state a single-field call cannot have. */
export function SessionPanel({
  session,
  onNextPage,
  onEnd,
}: {
  session: ApplicationSession | null
  onNextPage: () => void
  onEnd: () => void
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
