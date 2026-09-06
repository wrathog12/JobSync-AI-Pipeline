import { useState } from 'react'
import { api, type RecordPatch } from './api'
import { Bullets, Choice, Field, SaveBar, TextList, changedOnly, orNull, text, useSave } from './fields'
import type { Credential, Education, Employment, Project } from './types.generated'

/** The four kinds of thing your history is made of, each one editable in place.
 *
 * Every card is mounted with `key={record.id}` by its parent, which is load-bearing:
 * saving does not mutate a record, it supersedes it with a corrected copy under a
 * new id. So the card unmounts and a fresh one mounts holding the saved values,
 * and there is no stale draft left over pointing at a record that just went
 * inactive.
 */

const DATE_HINT = 'YYYY-MM, e.g. 2023-04'

function Card({
  title,
  subtitle,
  children,
  onRemove,
  removeLabel,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  onRemove: () => void
  removeLabel: string
}) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="rec">
      <div className="rechead">
        <div>
          <h4>{title}</h4>
          {subtitle && <div className="sub2">{subtitle}</div>}
        </div>
        {confirming ? (
          <div className="pick">
            <button type="button" className="danger" onClick={onRemove}>
              {removeLabel}
            </button>
            <button type="button" onClick={() => setConfirming(false)}>
              Keep it
            </button>
          </div>
        ) : (
          <button type="button" className="x big" title="remove" onClick={() => setConfirming(true)}>
            ×
          </button>
        )}
      </div>
      {confirming && (
        <div className="hint warn">
          This takes it out of everything that gets written from now on. It is not deleted — if you
          already sent an application built on it, that record still explains what you said.
        </div>
      )}
      {children}
    </div>
  )
}

/** Saving hands back a *new* id, so the parent has to reload rather than patch its
 * own copy. Both callbacks fire: `onChange` reloads, and the card is gone. */
function useRecordSave(id: string, onChange: () => void) {
  const saver = useSave(onChange)
  return {
    ...saver,
    commit: (patch: RecordPatch) => saver.save(() => api.editRecord(id, patch)),
    remove: () => saver.save(() => api.removeRecord(id)),
  }
}

const bullets = (items: string[]) => items.map((t) => t.trim()).filter(Boolean)

// ── jobs ───────────────────────────────────────────────────────────────────────

const JOB_TYPES = [
  { value: 'full_time', label: 'Full time' },
  { value: 'part_time', label: 'Part time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
  { value: 'freelance', label: 'Freelance' },
  { value: 'volunteer', label: 'Volunteer' },
] as const

export function JobCard({ job, onChange }: { job: Employment; onChange: () => void }) {
  const initial = {
    employer: job.employer,
    title: job.title,
    employment_type: job.employment_type as string,
    location: text(job.location),
    summary: text(job.summary),
    start: text(job.dates.start),
    end: text(job.dates.end),
    achievements: job.achievements.map((a) => a.text),
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, commit, remove } = useRecordSave(job.id, onChange)
  const set = (k: keyof typeof initial, v: unknown) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)

  const save = () => {
    const patch: RecordPatch = {}
    if ('employer' in changed) patch.employer = orNull(draft.employer)
    if ('title' in changed) patch.title = orNull(draft.title)
    if ('location' in changed) patch.location = orNull(draft.location)
    if ('summary' in changed) patch.summary = orNull(draft.summary)
    if ('start' in changed) patch.start = orNull(draft.start)
    if ('end' in changed) patch.end = orNull(draft.end)
    if ('achievements' in changed) patch.achievements = bullets(draft.achievements)
    // `employment_type` is an enum on the server; it has no "unset", so it is
    // always a real value and never nulled.
    if ('employment_type' in changed)
      (patch as Record<string, unknown>).employment_type = draft.employment_type
    commit(patch)
  }

  return (
    <Card
      title={`${job.title} · ${job.employer}`}
      subtitle={`${job.dates.start ?? '?'} → ${job.dates.end ?? 'now'}${
        job.location ? ` · ${job.location}` : ''
      }`}
      onRemove={remove}
      removeLabel="I never worked here"
    >
      <div className="grid">
        <Field label="Job title" value={draft.title} onChange={(v) => set('title', v)} />
        <Field label="Employer" value={draft.employer} onChange={(v) => set('employer', v)} />
        <Field label="Started" value={draft.start} onChange={(v) => set('start', v)} placeholder={DATE_HINT} />
        <Field
          label="Ended"
          value={draft.end}
          onChange={(v) => set('end', v)}
          placeholder="leave empty if you still work here"
          hint={draft.end.trim() ? undefined : 'Empty means this is your current job.'}
        />
        <Field label="Where" value={draft.location} onChange={(v) => set('location', v)} placeholder="City, or Remote" />
        <Choice
          label="Type"
          value={draft.employment_type}
          options={JOB_TYPES}
          onChange={(v) => set('employment_type', v)}
        />
        <Field
          label="What the role was"
          value={draft.summary}
          onChange={(v) => set('summary', v)}
          rows={2}
          wide
          placeholder="One line of context for the bullets below."
        />
      </div>
      <Bullets items={draft.achievements} onChange={(v) => set('achievements', v)} />
      <SaveBar dirty={Object.keys(changed).length > 0} busy={busy} error={error} onSave={save} onReset={() => setDraft(initial)} />
    </Card>
  )
}

// ── education ──────────────────────────────────────────────────────────────────

export function EducationCard({ edu, onChange }: { edu: Education; onChange: () => void }) {
  const initial = {
    institution: edu.institution,
    degree: edu.degree,
    field_of_study: text(edu.field_of_study),
    gpa: edu.gpa == null ? '' : String(edu.gpa),
    start: text(edu.dates.start),
    end: text(edu.dates.end),
    honors: edu.honors,
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, commit, remove } = useRecordSave(edu.id, onChange)
  const set = (k: keyof typeof initial, v: unknown) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)

  const save = () => {
    const patch: RecordPatch = {}
    if ('institution' in changed) patch.institution = orNull(draft.institution)
    if ('degree' in changed) patch.degree = orNull(draft.degree)
    if ('field_of_study' in changed) patch.field_of_study = orNull(draft.field_of_study)
    if ('start' in changed) patch.start = orNull(draft.start)
    if ('end' in changed) patch.end = orNull(draft.end)
    if ('honors' in changed) patch.honors = bullets(draft.honors)
    // A blank GPA is `null`, and `null` here means "not stated" rather than zero.
    // Forms ask for it, and answering 0.0 because nobody recorded it is worse than
    // being asked.
    if ('gpa' in changed) patch.gpa = draft.gpa.trim() ? Number(draft.gpa) : null
    commit(patch)
  }

  return (
    <Card
      title={`${edu.degree}${edu.field_of_study ? `, ${edu.field_of_study}` : ''}`}
      subtitle={`${edu.institution} · ${edu.dates.end ?? 'in progress'}`}
      onRemove={remove}
      removeLabel="I never studied here"
    >
      <div className="grid">
        <Field label="Degree" value={draft.degree} onChange={(v) => set('degree', v)} />
        <Field label="Subject" value={draft.field_of_study} onChange={(v) => set('field_of_study', v)} />
        <Field label="School" value={draft.institution} onChange={(v) => set('institution', v)} wide />
        <Field label="Started" value={draft.start} onChange={(v) => set('start', v)} placeholder={DATE_HINT} />
        <Field label="Finished" value={draft.end} onChange={(v) => set('end', v)} placeholder={DATE_HINT} />
        <Field
          label="GPA"
          type="number"
          value={draft.gpa}
          onChange={(v) => set('gpa', v)}
          placeholder="leave empty if you would rather not say"
          hint="Empty is a real answer. Forms that ask will get asked back rather than guessed at."
        />
      </div>
      <TextList label="Honours" items={draft.honors} onChange={(v) => set('honors', v)} placeholder="Dean's list, first class…" />
      <SaveBar dirty={Object.keys(changed).length > 0} busy={busy} error={error} onSave={save} onReset={() => setDraft(initial)} />
    </Card>
  )
}

// ── projects ───────────────────────────────────────────────────────────────────

export function ProjectCard({ project, onChange }: { project: Project; onChange: () => void }) {
  const initial = {
    name: project.name,
    role: text(project.role),
    summary: text(project.summary),
    url: text(project.url),
    start: text(project.dates.start),
    end: text(project.dates.end),
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, commit, remove } = useRecordSave(project.id, onChange)
  const set = (k: keyof typeof initial, v: unknown) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)

  const save = () => {
    const patch: RecordPatch = {}
    if ('name' in changed) patch.name = orNull(draft.name)
    if ('role' in changed) patch.role = orNull(draft.role)
    if ('summary' in changed) patch.summary = orNull(draft.summary)
    if ('url' in changed) patch.url = orNull(draft.url)
    if ('start' in changed) patch.start = orNull(draft.start)
    if ('end' in changed) patch.end = orNull(draft.end)
    commit(patch)
  }

  return (
    <Card
      title={project.name}
      subtitle={project.employer_id ? 'built at work' : 'your own'}
      onRemove={remove}
      removeLabel="This is not mine"
    >
      <div className="grid">
        <Field label="Name" value={draft.name} onChange={(v) => set('name', v)} />
        <Field label="Your part in it" value={draft.role} onChange={(v) => set('role', v)} />
        <Field label="What it is" value={draft.summary} onChange={(v) => set('summary', v)} rows={2} wide />
        <Field label="Link" value={draft.url} onChange={(v) => set('url', v)} placeholder="https://" wide />
        <Field label="Started" value={draft.start} onChange={(v) => set('start', v)} placeholder={DATE_HINT} />
        <Field label="Finished" value={draft.end} onChange={(v) => set('end', v)} placeholder="empty if ongoing" />
      </div>
      <SaveBar dirty={Object.keys(changed).length > 0} busy={busy} error={error} onSave={save} onReset={() => setDraft(initial)} />
    </Card>
  )
}

// ── credentials ────────────────────────────────────────────────────────────────

export function CredentialCard({ cred, onChange }: { cred: Credential; onChange: () => void }) {
  const initial = {
    name: cred.name,
    issuer: cred.issuer,
    issued: text(cred.issued),
    expires: text(cred.expires),
    credential_id: text(cred.credential_id),
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, commit, remove } = useRecordSave(cred.id, onChange)
  const set = (k: keyof typeof initial, v: unknown) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)

  const save = () => {
    const patch: RecordPatch = {}
    if ('name' in changed) patch.name = orNull(draft.name)
    if ('issuer' in changed) patch.issuer = orNull(draft.issuer)
    if ('issued' in changed) patch.issued = orNull(draft.issued)
    if ('expires' in changed) patch.expires = orNull(draft.expires)
    if ('credential_id' in changed) patch.credential_id = orNull(draft.credential_id)
    commit(patch)
  }

  return (
    <Card
      title={cred.name}
      subtitle={`${cred.issuer}${cred.issued ? ` · ${cred.issued}` : ''}`}
      onRemove={remove}
      removeLabel="I do not hold this"
    >
      <div className="grid">
        <Field label="Certification" value={draft.name} onChange={(v) => set('name', v)} />
        <Field label="Who issued it" value={draft.issuer} onChange={(v) => set('issuer', v)} />
        <Field label="Issued" value={draft.issued} onChange={(v) => set('issued', v)} placeholder={DATE_HINT} />
        <Field label="Expires" value={draft.expires} onChange={(v) => set('expires', v)} placeholder="empty if it doesn't" />
        <Field label="Reference number" value={draft.credential_id} onChange={(v) => set('credential_id', v)} wide />
      </div>
      <SaveBar dirty={Object.keys(changed).length > 0} busy={busy} error={error} onSave={save} onReset={() => setDraft(initial)} />
    </Card>
  )
}
