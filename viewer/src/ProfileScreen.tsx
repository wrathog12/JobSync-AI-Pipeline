import { useState } from 'react'
import { api, type MemoryView, type SkillView } from './api'
import { Choice, Field, SaveBar, Tristate, changedOnly, orNull, text, useSave } from './fields'
import { CredentialCard, EducationCard, JobCard, ProjectCard } from './Records'
import type { AuthorizationStatus, RemotePreference } from './types.generated'

/** Everything the system knows about you, in the order a person would look for it,
 * with every field editable where it sits.
 *
 * The one thing this screen has to get right is that *this is the source of truth*.
 * A form filled in on a job site is filled in from here; a résumé is written from
 * here. So it shows all of it — including the fields that are empty, because an
 * empty work-authorization block is the reason an application stalls asking about
 * sponsorship, and a page that hid it would leave that unexplained.
 */

/** The two flags every ledger record carries. The generated types do not emit the
 * base class, so this names the part that matters here rather than casting. */
type Flagged = { superseded_by: string | null; retracted_at: string | null }

/** Superseded and retracted records are on disk for the audit trail, and are not
 * what anyone means by "my profile". Retrieval already ignores them; so does this. */
const active = <T extends Flagged>(rows: T[]): T[] =>
  rows.filter((r) => r.superseded_by === null && r.retracted_at === null)

export function ProfileScreen({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const jobs = active(memory.ledger.employment)
  const education = active(memory.ledger.education)
  const projects = active(memory.ledger.projects)
  const credentials = active(memory.ledger.credentials)

  if (memory.is_empty) {
    return (
      <div className="empty big">
        Nothing here yet. Upload a résumé on the first screen and everything it finds will show up
        here, editable.
      </div>
    )
  }

  return (
    <>
      <IdentityCard memory={memory} onChange={onChange} />
      <ContactCard memory={memory} onChange={onChange} />
      <AuthorizationCard memory={memory} onChange={onChange} />
      <PreferencesCard memory={memory} onChange={onChange} />

      <Section title="Where you have worked" count={jobs.length}>
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} onChange={onChange} />
        ))}
      </Section>

      <Section title="Education" count={education.length}>
        {education.map((edu) => (
          <EducationCard key={edu.id} edu={edu} onChange={onChange} />
        ))}
      </Section>

      <Section title="Projects" count={projects.length}>
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} onChange={onChange} />
        ))}
      </Section>

      <Section title="Certifications" count={credentials.length}>
        {credentials.map((c) => (
          <CredentialCard key={c.id} cred={c} onChange={onChange} />
        ))}
      </Section>

      <SkillsCard memory={memory} onChange={onChange} />
    </>
  )
}

function Section({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  if (count === 0) return null
  return (
    <section>
      <h2>
        {title} <span className="count">{count}</span>
      </h2>
      {children}
    </section>
  )
}

// ── L0: your name ──────────────────────────────────────────────────────────────

function IdentityCard({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const id = memory.identity
  const initial = {
    legal_first: text(id?.legal_first),
    legal_middle: text(id?.legal_middle),
    legal_last: text(id?.legal_last),
    preferred_name: text(id?.preferred_name),
    pronouns: text(id?.pronouns),
    date_of_birth: text(id?.date_of_birth),
    citizenship: (id?.citizenship ?? []).join(', '),
  }
  const [draft, setDraft] = useState(initial)
  const [unlock, setUnlock] = useState(false)
  const { busy, error, save } = useSave(onChange)
  const set = (k: keyof typeof initial, v: string) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)
  const dirty = Object.keys(changed).length > 0

  const submit = () =>
    save(async () => {
      const patch: Record<string, unknown> = {}
      for (const key of Object.keys(changed)) {
        patch[key] =
          key === 'citizenship'
            ? draft.citizenship
                .split(',')
                .map((s) => s.trim().toUpperCase())
                .filter(Boolean)
            : orNull(draft[key as keyof typeof draft])
      }
      await api.editIdentity(patch, unlock)
      setUnlock(false)
    })

  const locked = Boolean(id?.locked)
  const nameChanged = 'legal_first' in changed || 'legal_middle' in changed || 'legal_last' in changed

  return (
    <section>
      <h2>
        Your name{locked && <span className="pill ok">locked</span>}
      </h2>
      <div className="rec">
        <div className="grid">
          <Field label="First (legal)" value={draft.legal_first} onChange={(v) => set('legal_first', v)} />
          <Field label="Middle" value={draft.legal_middle} onChange={(v) => set('legal_middle', v)} />
          <Field label="Last (legal)" value={draft.legal_last} onChange={(v) => set('legal_last', v)} />
          <Field
            label="What you go by"
            value={draft.preferred_name}
            onChange={(v) => set('preferred_name', v)}
            hint="Used where a form asks for a display name rather than a legal one."
          />
          <Field
            label="Pronouns"
            value={draft.pronouns}
            onChange={(v) => set('pronouns', v)}
            hint="Only ever what you put here. Never guessed from a name."
          />
          <Field
            label="Date of birth"
            type="date"
            value={draft.date_of_birth}
            onChange={(v) => set('date_of_birth', v)}
          />
          <Field
            label="Citizenship"
            value={draft.citizenship}
            onChange={(v) => set('citizenship', v)}
            placeholder="IN, US"
            hint="Two-letter country codes, comma separated."
          />
        </div>

        {locked && nameChanged && (
          <label className="check warn">
            <input type="checkbox" checked={unlock} onChange={(e) => setUnlock(e.target.checked)} />
            <span>
              Yes, change my legal name. It is locked because everything signed uses it — marriage,
              naturalisation and a bad first parse are all real reasons, and none of them should
              happen by accident.
            </span>
          </label>
        )}

        <SaveBar
          dirty={dirty}
          busy={busy}
          error={error}
          onSave={submit}
          onReset={() => setDraft(initial)}
        />
      </div>
    </section>
  )
}

// ── L1: contact ────────────────────────────────────────────────────────────────

function ContactCard({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const p = memory.profile
  const initial = {
    email: text(p?.email),
    phone_e164: text(p?.phone_e164),
    city: text(p?.location.city),
    region: text(p?.location.region),
    country: text(p?.location.country),
    postal: text(p?.location.postal),
    linkedin: text(p?.links.linkedin),
    github: text(p?.links.github),
    portfolio: text(p?.links.portfolio),
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, save } = useSave(onChange)
  const set = (k: keyof typeof initial, v: string) => setDraft({ ...draft, [k]: v })
  const changed = changedOnly(initial, draft)

  const submit = () =>
    save(() => {
      const patch: Record<string, unknown> = {}
      if ('email' in changed) patch.email = orNull(draft.email)
      if ('phone_e164' in changed) patch.phone_e164 = orNull(draft.phone_e164)
      // `location` and `links` are sub-objects on the server, so they go whole —
      // which is safe only because every one of their fields is on this card. A
      // partial object here would blank whatever was left out.
      if (['city', 'region', 'country', 'postal'].some((k) => k in changed))
        patch.location = {
          city: orNull(draft.city),
          region: orNull(draft.region),
          country: orNull(draft.country),
          postal: orNull(draft.postal),
        }
      if (['linkedin', 'github', 'portfolio'].some((k) => k in changed))
        patch.links = {
          linkedin: orNull(draft.linkedin),
          github: orNull(draft.github),
          portfolio: orNull(draft.portfolio),
          other: p?.links.other ?? {},
        }
      return api.editProfile(patch as never)
    })

  return (
    <section>
      <h2>How to reach you</h2>
      <div className="rec">
        <div className="grid">
          <Field label="Email" type="email" value={draft.email} onChange={(v) => set('email', v)} />
          <Field
            label="Phone"
            value={draft.phone_e164}
            onChange={(v) => set('phone_e164', v)}
            placeholder="+911234567890"
            hint="With the country code — that is the form most applications want."
          />
          <Field label="City" value={draft.city} onChange={(v) => set('city', v)} />
          <Field label="State or region" value={draft.region} onChange={(v) => set('region', v)} />
          <Field label="Country" value={draft.country} onChange={(v) => set('country', v)} />
          <Field label="Postcode" value={draft.postal} onChange={(v) => set('postal', v)} />
          <Field label="LinkedIn" value={draft.linkedin} onChange={(v) => set('linkedin', v)} wide />
          <Field label="GitHub" value={draft.github} onChange={(v) => set('github', v)} wide />
          <Field label="Website" value={draft.portfolio} onChange={(v) => set('portfolio', v)} wide />
        </div>
        <SaveBar
          dirty={Object.keys(changed).length > 0}
          busy={busy}
          error={error}
          onSave={submit}
          onReset={() => setDraft(initial)}
        />
      </div>
    </section>
  )
}

// ── L1: work authorization ─────────────────────────────────────────────────────

const AUTH_STATUS = [
  { value: 'unknown', label: "Haven't said" },
  { value: 'citizen', label: 'Citizen' },
  { value: 'permanent_resident', label: 'Permanent resident' },
  { value: 'visa', label: 'On a visa' },
  { value: 'none', label: 'Not authorised to work there' },
] as const

function AuthorizationCard({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const a = memory.profile?.authorization
  const initial = {
    country: text(a?.country),
    status: (a?.status ?? 'unknown') as AuthorizationStatus,
    requires_sponsorship: a?.requires_sponsorship ?? null,
    work_permit_expiry: text(a?.work_permit_expiry),
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, save } = useSave(onChange)
  const changed = changedOnly(initial as never, draft as never)

  const submit = () =>
    save(() =>
      api.editProfile({
        authorization: {
          country: orNull(draft.country),
          status: draft.status,
          requires_sponsorship: draft.requires_sponsorship,
          work_permit_expiry: orNull(draft.work_permit_expiry),
        },
      } as never)
    )

  return (
    <section>
      <h2>Right to work</h2>
      <div className="rec">
        <p className="lead">
          This is the one thing a résumé can never tell us, and the one thing nothing here will ever
          guess. Working in a country does not mean being allowed to work there without sponsorship —
          that assumption is wrong for a lot of people, and it is wrong in the direction that gets an
          offer withdrawn. So it is blank until you fill it in, and until then applications ask you
          instead of answering for you.
        </p>
        <div className="grid">
          <Choice
            label="Status"
            value={draft.status}
            options={AUTH_STATUS}
            onChange={(v) => setDraft({ ...draft, status: v })}
          />
          <Field
            label="In which country"
            value={draft.country}
            onChange={(v) => setDraft({ ...draft, country: v })}
            placeholder="IN"
          />
          <Tristate
            label="Do you need sponsorship?"
            value={draft.requires_sponsorship}
            onChange={(v) => setDraft({ ...draft, requires_sponsorship: v })}
          />
          <Field
            label="Permit expires"
            value={draft.work_permit_expiry}
            onChange={(v) => setDraft({ ...draft, work_permit_expiry: v })}
            placeholder="YYYY-MM-DD"
          />
        </div>
        <SaveBar
          dirty={Object.keys(changed).length > 0}
          busy={busy}
          error={error}
          onSave={submit}
          onReset={() => setDraft(initial)}
        >
          {memory.stats.stale_paths.includes('authorization') && (
            <span className="pill thin">worth re-checking — it has been a while</span>
          )}
        </SaveBar>
      </div>
    </section>
  )
}

// ── L1: preferences ────────────────────────────────────────────────────────────

const REMOTE = [
  { value: 'no_preference', label: 'No preference' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'On site' },
] as const

function PreferencesCard({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const pref = memory.profile?.preferences
  const initial = {
    remote_preference: (pref?.remote_preference ?? 'no_preference') as RemotePreference,
    notice_period_days: pref?.notice_period_days == null ? '' : String(pref.notice_period_days),
    earliest_start: text(pref?.earliest_start),
    willing_to_relocate: pref?.willing_to_relocate ?? null,
    amount: pref?.desired_comp ? String(pref.desired_comp.amount) : '',
    currency: pref?.desired_comp?.currency ?? 'INR',
  }
  const [draft, setDraft] = useState(initial)
  const { busy, error, save } = useSave(onChange)
  const changed = changedOnly(initial as never, draft as never)

  const submit = () =>
    save(() =>
      api.editProfile({
        preferences: {
          remote_preference: draft.remote_preference,
          notice_period_days: draft.notice_period_days.trim()
            ? Number(draft.notice_period_days)
            : null,
          earliest_start: orNull(draft.earliest_start),
          willing_to_relocate: draft.willing_to_relocate,
          desired_comp: draft.amount.trim()
            ? { amount: Number(draft.amount), currency: draft.currency || 'INR', basis: 'annual' }
            : null,
        },
      } as never)
    )

  return (
    <section>
      <h2>What you are looking for</h2>
      <div className="rec">
        <div className="grid">
          <Choice
            label="Where you want to work"
            value={draft.remote_preference}
            options={REMOTE}
            onChange={(v) => setDraft({ ...draft, remote_preference: v })}
          />
          <Field
            label="Notice period (days)"
            type="number"
            value={draft.notice_period_days}
            onChange={(v) => setDraft({ ...draft, notice_period_days: v })}
          />
          <Field
            label="Earliest you could start"
            type="date"
            value={draft.earliest_start}
            onChange={(v) => setDraft({ ...draft, earliest_start: v })}
          />
          <Tristate
            label="Would you relocate?"
            value={draft.willing_to_relocate}
            onChange={(v) => setDraft({ ...draft, willing_to_relocate: v })}
          />
          <Field
            label="Expected salary (per year)"
            type="number"
            value={draft.amount}
            onChange={(v) => setDraft({ ...draft, amount: v })}
            hint="Empty means an application will ask you rather than put a number in."
          />
          <Field
            label="Currency"
            value={draft.currency}
            onChange={(v) => setDraft({ ...draft, currency: v.toUpperCase() })}
            placeholder="INR"
          />
        </div>
        <SaveBar
          dirty={Object.keys(changed).length > 0}
          busy={busy}
          error={error}
          onSave={submit}
          onReset={() => setDraft(initial)}
        />
      </div>
    </section>
  )
}

// ── L4: skills ─────────────────────────────────────────────────────────────────

function SkillsCard({ memory, onChange }: { memory: MemoryView; onChange: () => void }) {
  const [adding, setAdding] = useState('')
  const { busy, error, save, clearError } = useSave(onChange)

  const declared = new Set(memory.declared_skills.map((s) => s.id))
  const inferred = memory.skills.filter((s) => !declared.has(s.id))

  return (
    <section>
      <h2>
        Skills <span className="count">{memory.skills.length}</span>
      </h2>
      <div className="rec">
        <p className="lead">
          A typo here is the quietest way to lose an application: matching is by word, so
          <code> Pyhton </code> simply stops matching a job asking for Python, and nothing anywhere
          looks broken.
        </p>

        <div className="chips">
          {memory.declared_skills.map((skill) => (
            <SkillChip key={skill.id} skill={skill} onChange={onChange} />
          ))}
        </div>

        <div className="addrow">
          <input
            value={adding}
            placeholder="add a skill"
            onChange={(e) => {
              setAdding(e.target.value)
              clearError()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && adding.trim())
                save(() => api.addSkill(adding.trim())).then((ok) => ok && setAdding(''))
            }}
          />
          <button
            className="btn sm"
            disabled={busy || !adding.trim()}
            onClick={() => save(() => api.addSkill(adding.trim())).then((ok) => ok && setAdding(''))}
          >
            Add
          </button>
        </div>
        {error && <div className="err">{error}</div>}

        {inferred.length > 0 && (
          <div className="inferred">
            <label>Also picked up from what you wrote</label>
            <div className="chips">
              {inferred.map((s) => (
                <span className="chip flat" key={s.id}>
                  {s.name}
                </span>
              ))}
            </div>
            <div className="hint">
              These are here because a bullet above mentions them, so they are not removable on their
              own — edit the bullet and they follow.
            </div>
          </div>
        )}

        {memory.stats.unbacked_skills.length > 0 && (
          <div className="hint warn">
            Nothing you have written demonstrates {memory.stats.unbacked_skills.join(', ')}. Listing a
            skill is not evidence of it, so these will not carry an answer on their own — a bullet
            that shows you using them will.
          </div>
        )}
      </div>
    </section>
  )
}

function SkillChip({ skill, onChange }: { skill: SkillView; onChange: () => void }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(skill.name)
  const { busy, save } = useSave(onChange)

  if (editing) {
    return (
      <span className="chip editing">
        <input
          autoFocus
          value={name}
          disabled={busy}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            if (name.trim() && name !== skill.name) save(() => api.renameSkill(skill.id, name.trim()))
            setEditing(false)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur()
            if (e.key === 'Escape') {
              setName(skill.name)
              setEditing(false)
            }
          }}
        />
      </span>
    )
  }

  return (
    <span className="chip">
      <button type="button" className="chipname" title="rename" onClick={() => setEditing(true)}>
        {skill.name}
      </button>
      {skill.evidence_ids.length === 0 && <span className="dot" title="nothing backs this yet" />}
      <button type="button" className="x" title="remove" onClick={() => save(() => api.removeSkill(skill.id))}>
        ×
      </button>
    </span>
  )
}
