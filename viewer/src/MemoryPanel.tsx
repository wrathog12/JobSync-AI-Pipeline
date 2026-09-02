import type { CompetencyInfo, MemoryView } from './api'

export function MemoryPanel({
  memory,
  competencies,
}: {
  memory: MemoryView | null
  competencies: CompetencyInfo[]
}) {
  if (!memory) return <div className="empty">Loading memory…</div>
  const s = memory.stats

  return (
    <div className="mem">
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
