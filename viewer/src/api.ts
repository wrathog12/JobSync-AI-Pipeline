import type {
  AnswerRequest,
  ApplicationSession,
  DocumentView,
  TraceView,
} from './types.generated'

const BASE = '/api'

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json() as Promise<T>
}

export type GenerationModeName = 'strict' | 'optimize' | 'aggressive'

export interface ModeInfo {
  mode: GenerationModeName
  max_claim_distance: number
  description: string
}

export interface CompetencyInfo {
  tag: string
  label: string
  evidence_count: number
  is_answerable: boolean
  is_thin: boolean
  is_soft: boolean
  strongest_chunk_id: string | null
}

export interface MemoryStats {
  identity_locked: boolean
  employment_records: number
  education_records: number
  project_records: number
  credential_records: number
  evidence_chunks: number
  skills: number
  unbacked_skills: string[]
  answerable_competencies: number
  competency_gaps: string[]
  thin_competencies: string[]
  approved_answers: number
  total_years_experience: number
  stale_paths: string[]
}

export interface EvidenceView {
  chunk_id: string
  text: string
  source_label: string
  entity_id: string
  competency_tags: string[]
  metrics: string[]
  confidence: string
  attributed_text: string
}

export interface MemoryView {
  identity: Record<string, unknown> | null
  profile: Record<string, unknown> | null
  ledger: Record<string, unknown>
  skills: Array<{ id: string; name: string; evidence_ids: string[]; years: number | null; proficiency: string | null }>
  evidence: EvidenceView[]
  stats: MemoryStats
}

export const api = {
  health: () => json<{ status: string; phase: number; memory: MemoryStats }>('/health'),
  modes: () => json<ModeInfo[]>('/meta/modes'),
  competencies: () => json<CompetencyInfo[]>('/meta/competencies'),
  memory: () => json<MemoryView>('/memory'),
  traces: () => json<TraceView[]>('/traces'),

  answer: (req: AnswerRequest) =>
    json<TraceView>('/answer', { method: 'POST', body: JSON.stringify(req) }),

  compare: (req: AnswerRequest) =>
    json<Record<GenerationModeName, TraceView>>('/answer/compare', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // ── L6 sessions: one application, many pages ──
  startSession: (body: { jd_text?: string | null; mode?: GenerationModeName; company?: string | null }) =>
    json<ApplicationSession>('/sessions', { method: 'POST', body: JSON.stringify(body) }),

  session: (id: string) => json<ApplicationSession>(`/sessions/${id}`),

  nextPage: (id: string) =>
    json<ApplicationSession>(`/sessions/${id}/next-page`, { method: 'POST' }),

  endSession: (id: string) =>
    json<{ dropped: boolean }>(`/sessions/${id}`, { method: 'DELETE' }),

  // ── ingest: documents in, text out ──
  upload: async (file: File) => {
    // No Content-Type header: the browser must set the multipart boundary itself,
    // and `json()` would override it with application/json.
    const body = new FormData()
    body.append('file', file)
    const res = await fetch(`${BASE}/ingest/upload`, { method: 'POST', body })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on /ingest/upload`)
    return (await res.json()) as DocumentView
  },

  paste: (text: string, filename?: string) =>
    json<DocumentView>('/ingest/paste', {
      method: 'POST',
      body: JSON.stringify({ text, filename: filename ?? null }),
    }),

  documents: () => json<DocumentView[]>('/ingest/documents'),
}
