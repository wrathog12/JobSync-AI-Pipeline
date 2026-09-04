import { api, type CompetencyInfo, type MemoryView, type StorageInfo } from './api'

export function MemoryPanel({
  memory,
  competencies,
  storage,
  onChange,
}: {
  memory: MemoryView | null
  competencies: CompetencyInfo[]
  storage?: StorageInfo | null
  onChange?: () => void
}) {
  if (!memory) return <div className="empty">Loading memory…</div>
  const s = memory.stats

  const swap = async (fn: () => Promise<unknown>) => {
    await fn()
    onChange?.()
  }

  return (
    <div className="mem">
      <div className="card wide">
        <h3>Whose memory is this?</h3>
        {memory.is_empty ? (
          <div className="src">
            Empty — nothing has been confirmed yet, which is the correct starting state. Ingest
            your résumé and confirm it on <strong>Review &amp; confirm</strong>, or load the demo
            profile to see retrieval work against someone else's career first.
          </div>
        ) : (
          <div className="src">
            Holding {s.employment_records} job{s.employment_records === 1 ? '' : 's'} and{' '}
            {s.evidence_chunks} evidence chunks
            {s.identity_locked ? ', with a locked identity' : ''}. If any of it is the demo
            profile's, clear it before confirming your own — the L0 lock will otherwise refuse
            your name in defence of a fictional person, and the ledger is append-only, so both
            people's jobs end up retrievable.
          </div>
        )}
        <div className="actions" style={{ paddingTop: 10 }}>
          <button className="btn ghost" onClick={() => swap(api.loadDemo)}>
            Load the demo profile
          </button>
          <button className="btn ghost" onClick={() => swap(api.clearMemory)}>
            Clear memory
          </button>
        </div>
        {storage === null ? (
          <div className="warnlist" style={{ marginTop: 10 }}>
            Storage is off — nothing you confirm will survive a restart. Set{' '}
            <code>DB_PATH</code> in <code>server/.env</code> to turn it on.
          </div>
        ) : (
          storage && (
            <div className="src" style={{ marginTop: 10 }}>
              On disk at <code>{storage.path}</code>: {storage.ledger_record} ledger row
              {storage.ledger_record === 1 ? '' : 's'}, {storage.declared_skill} skill
              {storage.declared_skill === 1 ? '' : 's'}, {storage.approved_answer} approved answer
              {storage.approved_answer === 1 ? '' : 's'}, {storage.document} document
              {storage.document === 1 ? '' : 's'} and {storage.candidate} pending review
              {storage.candidate === 1 ? '' : 's'}. The derived layers are absent on purpose —
              they are rebuilt from the ledger on every start.
            </div>
          )
        )}
      </div>

      <div className="card">
        <h3>Layers</h3>
        <dl className="kv">
          <dt>L0 identity</dt>
          <dd>{s.identity_locked ? 'locked ✓' : 'unlocked'}</dd>
          <dt>L1 profile</dt>
          <dd>
            {s.stale_paths.length === 0 ? (
              'all confirmed'
            ) : (
              <span className="warnlist">{s.stale_paths.length} stale: {s.stale_paths.join(', ')}</span>
            )}
          </dd>
          <dt>L2 ledger</dt>
          <dd>
            {s.employment_records} jobs · {s.education_records} edu · {s.project_records} proj ·{' '}
            {s.credential_records} cred
          </dd>
          <dt>L3 evidence</dt>
          <dd>{s.evidence_chunks} chunks</dd>
          <dt>L4 competency</dt>
          <dd>
            {s.skills} skills · {s.answerable_competencies}/{competencies.length} answerable
          </dd>
          <dt>L5 answers</dt>
          <dd>{s.approved_answers} approved</dd>
          <dt>experience</dt>
          <dd>{s.total_years_experience} years (computed, not generated)</dd>
        </dl>
      </div>

      <div className="card">
        <h3>Gaps the system will abstain on</h3>
        {s.competency_gaps.length === 0 ? (
          <div className="empty">No gaps.</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {s.competency_gaps.map((g) => (
              <span className="pill gap" key={g}>
                {g}
              </span>
            ))}
          </div>
        )}
        <h3 style={{ marginTop: 18 }}>Declared but unbacked skills</h3>
        {s.unbacked_skills.length === 0 ? (
          <div className="empty">Every skill has backing evidence.</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {s.unbacked_skills.map((g) => (
              <span className="pill thin" key={g}>
                {g}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="card wide">
        <h3>L4 — competencies (soft skills are counts, never checkmarks)</h3>
        <table className="t">
          <thead>
            <tr>
              <th>competency</th>
              <th>kind</th>
              <th>evidence</th>
              <th>status</th>
              <th>strongest chunk</th>
            </tr>
          </thead>
          <tbody>
            {competencies.map((c) => (
              <tr key={c.tag}>
                <td>{c.tag}</td>
                <td>
                  {c.is_soft ? <span className="pill soft">soft</span> : <span className="pill">hard</span>}
                </td>
                <td className="n">{c.evidence_count}</td>
                <td>
                  {!c.is_answerable ? (
                    <span className="pill gap">abstain</span>
                  ) : c.is_thin ? (
                    <span className="pill thin">thin</span>
                  ) : (
                    <span className="pill ok">ok</span>
                  )}
                </td>
                <td className="n">{c.strongest_chunk_id ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card wide">
        <h3>L4 — skills</h3>
        <table className="t">
          <thead>
            <tr>
              <th>skill</th>
              <th>years</th>
              <th>proficiency</th>
              <th>backing evidence</th>
            </tr>
          </thead>
          <tbody>
            {memory.skills.map((sk) => (
              <tr key={sk.id}>
                <td>{sk.name}</td>
                <td className="n">{sk.years ?? '—'}</td>
                <td className="n">{sk.proficiency ?? '—'}</td>
                <td className="n">
                  {sk.evidence_ids.length === 0 ? (
                    <span className="pill thin">unbacked — claim, not fact</span>
                  ) : (
                    sk.evidence_ids.join(', ')
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card wide">
        <h3>L3 — evidence chunks (as they enter a prompt)</h3>
        <table className="t">
          <thead>
            <tr>
              <th>chunk</th>
              <th>pre-attributed text</th>
              <th>tags</th>
            </tr>
          </thead>
          <tbody>
            {memory.evidence.map((e) => (
              <tr key={e.chunk_id}>
                <td className="n">{e.chunk_id}</td>
                <td style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--mono)', fontSize: 12 }}>
                  {e.attributed_text}
                </td>
                <td className="n">{e.competency_tags.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
