import type { TraceView } from './types.generated'

const STAGE_LABEL: Record<string, string> = {
  classify: 'classify',
  session_replay: 'session replay (L6)',
  answer_memory: 'answer memory (L5)',
  retrieve: 'retrieve (L3)',
  rerank: 'rerank',
  sufficiency_gate: '► sufficiency gate',
  generate: 'generate',
  length_repair: 'length repair',
  ground_check: '► ground check',
}

export function TraceCard({ trace, open = false }: { trace: TraceView; open?: boolean }) {
  const cls = trace.field.field_class
  const limit = trace.field.constraints?.max_value ?? null

  return (
    <details className="trace" open={open}>
      <summary>
        <div className="q">
          <div className="label">{trace.field.context_label}</div>
          <div className={`answer${trace.abstained ? ' abstain' : ''}`}>
            {trace.abstained ? `abstained — ${trace.abstain_reason ?? ''}` : trace.answer}
          </div>
        </div>
        <span className={`tag ${cls}`}>{cls}</span>
        <span className="tag mode">{trace.mode}</span>
        {trace.chars > 0 && (
          <span className="tag chars">
            {trace.chars}
            {limit ? `/${limit}` : ''} ch
          </span>
        )}
        {trace.needs_review && <span className="tag attestation">needs review</span>}
      </summary>

      <div className="body">
        <div className={`answerbox${trace.abstained ? ' abstain' : ''}`}>
          {trace.abstained ? trace.abstain_reason : trace.answer}
        </div>

        {trace.steps.map((step, i) => (
          <div className="stage" key={i}>
            <div>
              <div className="name">{STAGE_LABEL[step.stage] ?? step.stage}</div>
              {step.ms ? <div className="ms">{step.ms} ms</div> : null}
            </div>
            <div className={`st ${step.status}`}>{step.status}</div>
            <div>
              <div className="detail">{step.detail}</div>

              {step.chunks && step.chunks.length > 0 && (
                <div className="chunks">
                  {step.chunks.map((c) => (
                    <div className="chunk" key={c.chunk_id}>
                      <div className="score">{c.score.toFixed(3)}</div>
                      <div>
                        <div className="src">
                          {c.chunk_id} · {c.source_label}
                        </div>
                        <div className="txt">{c.text_preview}</div>
                        {c.competency_overlap && c.competency_overlap.length > 0 && (
                          <div className="ctags">↳ tag match: {c.competency_overlap.join(', ')}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {step.violations && step.violations.length > 0 && (
                <div className="violations">
                  {step.violations.map((v, k) => (
                    <div className="violation" key={k}>
                      ✗ {v.token} ({v.kind}) — {v.note}
                    </div>
                  ))}
                </div>
              )}

              {step.prompt_preview && (
                <details>
                  <summary className="src" style={{ cursor: 'pointer', color: 'var(--accent)' }}>
                    view prompt sent
                  </summary>
                  <pre className="prompt">{step.prompt_preview}</pre>
                </details>
              )}
            </div>
          </div>
        ))}

        {trace.stretches && trace.stretches.length > 0 && (
          <>
            <div className="stage">
              <div className="name">claim stretches</div>
              <div className="st stub">{trace.claim_distance.toFixed(2)}</div>
              <div className="detail">
                ceiling for {trace.mode} is {trace.max_claim_distance.toFixed(2)}
              </div>
            </div>
            {trace.stretches.map((s, i) => (
              <div className="stretchrow" key={i}>
                ↗ {s.claim} <span className="n">[{s.distance.toFixed(2)}]</span>
                <div className="note">{s.note}</div>
              </div>
            ))}
          </>
        )}

        {trace.spent_chunks_avoided.length > 0 && (
          <div className="stage">
            <div className="name">avoided (L6)</div>
            <div className="st skipped">spent</div>
            <div className="detail">
              {trace.spent_chunks_avoided.join(', ')} — already used elsewhere in this application
            </div>
          </div>
        )}

        <div className="footer">
          <span>{trace.trace_id}</span>
          {trace.session_id && (
            <span>
              {trace.session_id} · page {trace.page_index}
            </span>
          )}
          <span>{trace.total_ms} ms total</span>
          <span>
            {trace.total_tokens} tokens
            {trace.cached_tokens ? ` (${trace.cached_tokens} cached)` : ''}
          </span>
          <span>via {trace.field.classified_via}</span>
          {trace.field.canonical_question_id && <span>qid: {trace.field.canonical_question_id}</span>}
          {trace.field.profile_path && <span>path: {trace.field.profile_path}</span>}
        </div>
      </div>
    </details>
  )
}
