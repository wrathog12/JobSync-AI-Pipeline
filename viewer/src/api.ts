import type {
  AnswerRequest,
  ApplicationSession,
  ConfirmRequest,
  ConfirmView,
  Credential,
  DocumentView,
  Education,
  Employment,
  Identity,
  Ledger,
  Profile,
  Project,
  StructureView,
  TraceView,
} from './types.generated'

const BASE = '/api'

/** FastAPI puts everything useful in `detail`, and the LLM errors put a `blame`
 * and a written explanation inside that. Throwing the status line alone would
 * turn "that API key was rejected, copy it again" into "400 Bad Request". */
async function errorFrom(res: Response, path: string): Promise<Error> {
  let detail: unknown
  try {
    detail = (await res.json())?.detail
  } catch {
    /* not JSON — fall through to the status line */
  }
  if (typeof detail === 'string') return new Error(detail)
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const d = detail as { message: string; blame?: string }
    return new Error(d.blame ? `${d.message} (${d.blame})` : d.message)
  }
  return new Error(`${res.status} ${res.statusText} on ${path}`)
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw await errorFrom(res, path)
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

export interface SkillView {
  id: string
  name: string
  evidence_ids: string[]
  years: number | null
  proficiency: string | null
}

export interface MemoryView {
  identity: Identity | null
  profile: Profile | null
  ledger: Ledger
  /** The merged graph: declared skills plus the ones the bullets reference. */
  skills: SkillView[]
  /** The subset the user actually listed — and the only subset that can be
   * renamed or removed. An inferred skill is there because an achievement points
   * at it, so a delete button next to one would just 404. */
  declared_skills: SkillView[]
  evidence: EvidenceView[]
  stats: MemoryStats
  /** True until you confirm something. Not the same as "still loading". */
  is_empty: boolean
}

/** What the answer layer is configured with. Never the key itself. */
export interface LlmConfig {
  provider: string
  model_fast: string
  model_strong: string
  has_server_key: boolean
  require_user_key: boolean
  max_output_tokens: number
}

/** The fields a form actually has, flattened out of `DateRange` — nothing on the
 * page has a reason to know that type exists. Absent and `null` are different:
 * leaving `end` out means "don't touch it", sending `null` means "I still work
 * here". So this is built by hand from the inputs that changed, never spread
 * from a whole record. */
export interface RecordPatch {
  employer?: string | null
  title?: string | null
  location?: string | null
  summary?: string | null
  achievements?: string[]
  institution?: string | null
  degree?: string | null
  field_of_study?: string | null
  gpa?: number | null
  honors?: string[]
  name?: string | null
  role?: string | null
  url?: string | null
  issuer?: string | null
  issued?: string | null
  expires?: string | null
  credential_id?: string | null
  start?: string | null
  end?: string | null
}

export interface EditResult {
  memory: MemoryStats
  record?: Employment | Education | Project | Credential
  superseded?: string
  retracted?: string
  skill?: SkillView
  removed?: string
}

/** What is actually on disk. `null` means storage is switched off, which is a
 * supported configuration — and worth showing, because "my résumé disappeared
 * after a restart" and "storage is off" are otherwise the same symptom. */
export interface StorageInfo {
  path: string
  ledger_record: number
  declared_skill: number
  approved_answer: number
  document: number
  candidate: number
  /** Applications in progress. Not memory — but losing one loses half an hour of
   * the user's work, which is why it is on disk at all. */
  session: number
}

export interface Health {
  status: string
  phase: number
  memory_empty: boolean
  memory: MemoryStats
  storage: StorageInfo | null
}

export const api = {
  health: () => json<Health>('/health'),
  modes: () => json<ModeInfo[]>('/meta/modes'),
  competencies: () => json<CompetencyInfo[]>('/meta/competencies'),
  memory: () => json<MemoryView>('/memory'),
  llm: () => json<LlmConfig>('/meta/llm'),

  // ── editing what memory already holds ──
  // Every one of these is a supersede on the server, not an in-place write: the
  // old record stays, flagged, out of retrieval. That is why `editRecord` hands
  // back a *new* id — a caller still holding the old one is holding a record that
  // just went inactive.

  editRecord: (id: string, patch: RecordPatch) =>
    json<EditResult>(`/memory/records/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  /** Not a delete. It leaves retrieval and stays on disk, because an application
   * already sent somewhere may have been built on it. */
  removeRecord: (id: string) => json<EditResult>(`/memory/records/${id}`, { method: 'DELETE' }),

  editProfile: (patch: Partial<Profile>) =>
    json<EditResult & { profile: Profile }>('/memory/profile', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  /** `unlock` is deliberate rather than absent. Names change; they do not change
   * because the last document parsed said something else. */
  editIdentity: (patch: Partial<Identity>, unlock = false) =>
    json<EditResult & { identity: Identity }>(`/memory/identity?unlock=${unlock}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  addSkill: (name: string) =>
    json<EditResult>('/memory/skills', { method: 'POST', body: JSON.stringify({ name }) }),

  renameSkill: (id: string, name: string) =>
    json<EditResult>(`/memory/skills/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),

  removeSkill: (id: string) => json<EditResult>(`/memory/skills/${id}`, { method: 'DELETE' }),

  // Both destructive and both explicit. The demo profile used to load itself on
  // first read, which put a fictional person's locked identity in the way of the
  // real user's own name.
  loadDemo: () => json<{ loaded: boolean }>('/memory/demo', { method: 'POST' }),
  clearMemory: () => json<{ cleared: boolean }>('/memory', { method: 'DELETE' }),
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

  /** Attach (or replace) the job description on a session that already exists.
   * `stale_answers` is the number of answers written against the *previous* JD;
   * this call does not revise them, so it says how many are now out of date. */
  setSessionJd: (id: string, body: { jd_text: string; company?: string | null; role_title?: string | null }) =>
    json<ApplicationSession & { replaced: boolean; stale_answers: number }>(
      `/sessions/${id}/jd`,
      { method: 'POST', body: JSON.stringify(body) }
    ),

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

  // ── step 3: read a document into candidate records. Writes nothing. ──
  structure: (docId: string) =>
    json<StructureView>(`/structure/${docId}`, { method: 'POST' }),

  candidate: (docId: string) => json<StructureView>(`/structure/${docId}`),

  candidates: () => json<StructureView[]>('/structure'),

  discardCandidate: (docId: string) =>
    json<{ dropped: boolean }>(`/structure/${docId}`, { method: 'DELETE' }),

  // ── step 4: the only thing that writes to L0/L1/L2 ──
  confirm: (req: ConfirmRequest) =>
    json<ConfirmView>('/confirm', { method: 'POST', body: JSON.stringify(req) }),
}
