import { useCallback, useEffect, useState } from 'react'
import {
  api,
  type CompetencyInfo,
  type GenerationModeName,
  type MemoryView,
  type ModeInfo,
  type StorageInfo,
} from './api'
import { IngestPanel } from './IngestPanel'
import { MemoryPanel } from './MemoryPanel'
import { ReviewPanel } from './ReviewPanel'
import { SessionPanel } from './SessionPanel'
import { TraceCard } from './TraceCard'
import type { ApplicationSession, DocumentView, TraceView } from './types.generated'

const SAMPLES = [
  'What is your email address?',
  'Tell us about a time you had to influence stakeholders without direct authority.',
  'Describe a technical challenge you solved.',
  'Tell us about a time something went wrong and what you learned.',
  'Describe your experience managing a P&L.',
  'Do you require sponsorship to work in the United States?',
  'What is your GPA?',
]

const SAMPLE_JD = `Senior Platform Engineer — we run a high-volume payments platform.
You will own service reliability end to end. Required: 5+ years backend, deep
Kubernetes and Terraform experience, Go or Python, PostgreSQL at scale,
and a track record of driving cross-team technical decisions.`

type Tab = 'ask' | 'compare' | 'session' | 'ingest' | 'review' | 'memory' | 'traces'

const TAB_LABEL: Record<Tab, string> = {
  ask: 'Latest trace',
  compare: 'Mode comparison',
  session: 'Application',
  ingest: 'Ingest',
  review: 'Review & confirm',
  memory: 'Memory',
  traces: 'History',
}

/** A multi-page wizard, condensed: each entry is one "page" of one application. */
const WIZARD: { page: string; questions: string[] }[] = [
  {
    page: '1 — background',
    questions: ['Tell us about a time you led a team through a difficult migration.'],
  },
  {
    page: '2 — working style',
    questions: [
      'Describe a situation where you had to influence people without authority.',
      'Tell us about a time you mentored someone.',
    ],
  },
  {
    page: '3 — reliability',
    questions: ['Tell us about a time something went wrong and what you learned.'],
  },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('ask')
  const [question, setQuestion] = useState(SAMPLES[1])
  const [jd, setJd] = useState('')
  const [maxChars, setMaxChars] = useState(500)
  const [mode, setMode] = useState<GenerationModeName>('strict')

  const [modes, setModes] = useState<ModeInfo[]>([])
  const [competencies, setCompetencies] = useState<CompetencyInfo[]>([])
  const [memory, setMemory] = useState<MemoryView | null>(null)
  /** `undefined` = not asked yet, `null` = asked and storage is off. */
  const [storage, setStorage] = useState<StorageInfo | null | undefined>(undefined)

  const [trace, setTrace] = useState<TraceView | null>(null)
  const [compared, setCompared] = useState<Record<GenerationModeName, TraceView> | null>(null)
  const [traces, setTraces] = useState<TraceView[]>([])

  const [session, setSession] = useState<ApplicationSession | null>(null)
  const [doc, setDoc] = useState<DocumentView | null>(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.modes(), api.competencies(), api.memory(), api.documents(), api.health()])
      .then(([m, c, mem, docs, h]) => {
        setModes(m)
        setCompetencies(c)
        setMemory(mem)
        setStorage(h.storage)
        // Survive a page reload: the server still holds anything already extracted.
        if (docs.length) setDoc(docs[0])
      })
      .catch((e) => setError(String(e)))
  }, [])

  const refreshTraces = useCallback(() => {
    api.traces().then(setTraces).catch((e) => setError(String(e)))
  }, [])

  /** Confirming writes to L0-L2 and rebuilds L3/L4, so both of these move at once
   * — a stale competency list after a commit is how you end up debugging a
   * retrieval "bug" that is really a cached panel. */
  const refreshMemory = useCallback(() => {
    Promise.all([api.memory(), api.competencies(), api.health()])
      .then(([mem, c, h]) => {
        setMemory(mem)
        setCompetencies(c)
        // Health carries the on-disk counts, so a commit that reached memory but
        // not the database is visible here instead of at the next restart.
        setStorage(h.storage)
      })
      .catch((e) => setError(String(e)))
  }, [])

  const req = (overrides: Record<string, unknown> = {}) => ({
    question,
    mode,
    jd_text: jd || null,
    max_chars: maxChars,
    field_type: 'textarea',
    session_id: session?.session_id ?? null,
    ...overrides,
  })

  const refreshSession = useCallback(async (id: string) => {
    setSession(await api.session(id))
  }, [])

  const ask = async (overrides: Record<string, unknown> = {}) => {
    setBusy(true)
    setError(null)
    try {
      setTrace(await api.answer(req(overrides) as never))
      setCompared(null)
      setTab('ask')
      refreshTraces()
      if (session) await refreshSession(session.session_id)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const startSession = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = await api.startSession({ jd_text: jd || SAMPLE_JD, mode })
      if (!jd) setJd(SAMPLE_JD)
      setSession(s)
      setTab('session')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  /** Walk the whole wizard, so the multi-page behaviour is visible in one click. */
  const runWizard = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = session ?? (await api.startSession({ jd_text: jd || SAMPLE_JD, mode }))
      if (!jd) setJd(SAMPLE_JD)
      let current = s
      for (const [i, page] of WIZARD.entries()) {
        if (i > 0) current = await api.nextPage(current.session_id)
        for (const q of page.questions) {
          await api.answer({
            question: q,
            mode,
            max_chars: maxChars,
            field_type: 'textarea',
            session_id: current.session_id,
          } as never)
        }
      }
      setSession(await api.session(current.session_id))
      setTab('session')
      refreshTraces()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const compare = async () => {
    setBusy(true)
    setError(null)
    try {
      setCompared(await api.compare(req() as never))
      setTab('compare')
      refreshTraces()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="top">
        <h1>JobSync — Trace Viewer</h1>
        <span className="phase">phase 1</span>
      </header>
      <p className="sub">
        Everything except <strong>generate</strong> is the real pipeline: ingest, classification, the
        attestation deny-list, BM25 + competency retrieval, the sufficiency gate, the grounding
        check, and L6 session state across wizard pages. Generation is still a labelled stub — it
        concatenates retrieved evidence rather than writing prose, so judge the retrieval and the
        gate here, not the wording.
      </p>

      <div className="ask">
        <label>Question (any form label — it does not need to exist on a real page)</label>
        <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />

        <div className="row">
          <div style={{ flex: '2 1 300px' }}>
            <label>Sample questions</label>
            <select
              style={{
                width: '100%',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '9px 11px',
              }}
              value=""
              onChange={(e) => e.target.value && setQuestion(e.target.value)}
            >
              <option value="">pick one…</option>
              {SAMPLES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: '0 0 120px' }}>
            <label>Max chars</label>
            <input
              type="number"
              value={maxChars}
              onChange={(e) => setMaxChars(Number(e.target.value) || 500)}
            />
          </div>
          <div style={{ flex: '0 0 auto' }}>
            <label>Mode</label>
            <div className="modes">
              {modes.map((m) => (
                <button
                  key={m.mode}
                  data-active={mode === m.mode}
                  title={`${m.description} (max claim distance ${m.max_claim_distance})`}
                  onClick={() => setMode(m.mode)}
                >
                  {m.mode} <span style={{ opacity: 0.6 }}>{m.max_claim_distance.toFixed(2)}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <label>
            Job description (optional — disambiguates the question and drives skill matching)
          </label>
          <textarea rows={3} value={jd} onChange={(e) => setJd(e.target.value)} />
          <button
            className="btn ghost"
            style={{ marginTop: 6, padding: '5px 10px', fontSize: 12 }}
            onClick={() => setJd(SAMPLE_JD)}
          >
            use sample JD
          </button>
        </div>

        <div className="actions">
          <button className="btn" onClick={() => ask()} disabled={busy}>
            {busy ? 'running…' : 'Run'}
          </button>
          <button className="btn ghost" onClick={compare} disabled={busy}>
            Compare all 3 modes
          </button>
          {session && (
            <button
              className="btn ghost"
              onClick={() => ask({ regenerate: true })}
              disabled={busy}
              title="Bypass session replay and generate a fresh answer for this field"
            >
              Regenerate
            </button>
          )}
        </div>

        <div className="actions" style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          {session ? (
            <span className="phase">
              application {session.session_id} · page {session.page_index} ·{' '}
              {session.answered.length} fields
            </span>
          ) : (
            <button className="btn ghost" onClick={startSession} disabled={busy}>
              Start an application (L6)
            </button>
          )}
          <button className="btn ghost" onClick={runWizard} disabled={busy}>
            {busy ? 'running…' : 'Run the 3-page wizard'}
          </button>
        </div>
        {error && <div className="err">{error}</div>}
      </div>

      <div className="tabs">
        {(['ask', 'compare', 'session', 'ingest', 'review', 'memory', 'traces'] as Tab[]).map((t) => (
          <button
            key={t}
            data-active={tab === t}
            onClick={() => {
              setTab(t)
              if (t === 'traces') refreshTraces()
              if (t === 'session' && session) refreshSession(session.session_id)
            }}
          >
            {TAB_LABEL[t]}
            {t === 'session' && session ? ` (${session.answered.length})` : ''}
          </button>
        ))}
      </div>

      {tab === 'ask' &&
        (trace ? <TraceCard trace={trace} open /> : <div className="empty">Run a question above.</div>)}

      {tab === 'compare' &&
        (compared ? (
          <>
            <div className="compare">
              {(['strict', 'optimize', 'aggressive'] as GenerationModeName[]).map((m) => {
                const t = compared[m]
                return (
                  <div className="col" key={m}>
                    <h4>{m}</h4>
                    <div className="ceil">
                      ceiling {t.max_claim_distance.toFixed(2)} · actual{' '}
                      {t.claim_distance.toFixed(2)} · {t.chars} ch
                    </div>
                    <div className={`out${t.abstained ? ' abstain' : ''}`}>
                      {t.abstained ? t.abstain_reason : t.answer}
                    </div>
                    {t.stretches.length > 0 && (
                      <div style={{ marginTop: 10 }}>
                        {t.stretches.map((s, i) => (
                          <div className="stretchrow" key={i}>
                            ↗ {s.claim}
                            <div className="note">{s.note}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            {(['strict', 'optimize', 'aggressive'] as GenerationModeName[]).map((m) => (
              <TraceCard trace={compared[m]} key={m} />
            ))}
          </>
        ) : (
          <div className="empty">
            Hit “Compare all 3 modes”. Add a JD first — that is what gives the embellished modes
            something to stretch toward.
          </div>
        ))}

      {tab === 'session' && (
        <SessionPanel
          session={session}
          onNextPage={async () => {
            if (session) setSession(await api.nextPage(session.session_id))
          }}
          onEnd={async () => {
            if (session) await api.endSession(session.session_id)
            setSession(null)
          }}
        />
      )}

      {tab === 'ingest' && <IngestPanel doc={doc} onExtract={setDoc} />}

      {tab === 'review' && <ReviewPanel doc={doc} onCommitted={refreshMemory} />}

      {tab === 'memory' && (
        <MemoryPanel
          memory={memory}
          competencies={competencies}
          storage={storage}
          onChange={refreshMemory}
        />
      )}

      {tab === 'traces' &&
        (traces.length ? (
          traces.map((t) => <TraceCard trace={t} key={t.trace_id} />)
        ) : (
          <div className="empty">No traces yet.</div>
        ))}
    </div>
  )
}
