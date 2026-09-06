import { useState, type ReactNode } from 'react'

/** The form primitives every editable card on the page is built from.
 *
 * One decision shapes all of them: a card saves as a whole, on a button, rather
 * than each field saving itself when it loses focus. That looks less magical than
 * click-to-edit, and it is the honest shape for what happens underneath — a save
 * *supersedes* the record, appending a corrected copy and flagging the old one. A
 * field that saved on blur would leave one superseded copy per box the user
 * tabbed through, and a history reading as five corrections to one job.
 */

export function Field({
  label,
  value,
  onChange,
  placeholder,
  hint,
  type = 'text',
  rows,
  wide,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: ReactNode
  type?: 'text' | 'email' | 'number' | 'month' | 'date'
  rows?: number
  wide?: boolean
}) {
  return (
    <div className={`f${wide ? ' wide' : ''}`}>
      <label>{label}</label>
      {rows ? (
        <textarea rows={rows} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (v: T) => void
  hint?: ReactNode
}) {
  return (
    <div className="f">
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

/** Three states, not a checkbox.
 *
 * "Do you need sponsorship?" has a real third answer — nobody has told us — and a
 * checkbox spells that the same way as "no". The difference decides whether a form
 * gets filled in or the user gets asked, so it cannot be collapsed.
 */
export function Tristate({
  label,
  value,
  onChange,
  hint,
  yes = 'Yes',
  no = 'No',
}: {
  label: string
  value: boolean | null
  onChange: (v: boolean | null) => void
  hint?: ReactNode
  yes?: string
  no?: string
}) {
  return (
    <div className="f">
      <label>{label}</label>
      <div className="pick">
        {(
          [
            [true, yes],
            [false, no],
            [null, "Haven't said"],
          ] as [boolean | null, string][]
        ).map(([v, text]) => (
          <button key={String(v)} type="button" data-active={value === v} onClick={() => onChange(v)}>
            {text}
          </button>
        ))}
      </div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

/** The bullets under a job. Editable, addable, removable.
 *
 * Retyping one is allowed and is not a loophole in the grounding rules: those
 * exist to stop *model* prose becoming a permanent fact about someone's career.
 * A sentence the user wrote about their own work is the best evidence the system
 * has, and it is stored as their own words.
 */
export function Bullets({
  items,
  onChange,
}: {
  items: string[]
  onChange: (next: string[]) => void
}) {
  const set = (i: number, text: string) => onChange(items.map((t, j) => (j === i ? text : t)))
  return (
    <div className="bullets">
      <label>What you did here</label>
      {items.map((text, i) => (
        <div className="bullet" key={i}>
          <textarea rows={2} value={text} onChange={(e) => set(i, e.target.value)} />
          <button
            type="button"
            className="x"
            title="remove this bullet"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn ghost sm" onClick={() => onChange([...items, ''])}>
        + add a bullet
      </button>
      {items.length === 0 && (
        <div className="hint">
          Nothing here yet. Without bullets this job can confirm dates and a title, and not much
          else — the answers come from what you actually did.
        </div>
      )}
    </div>
  )
}

/** A short editable list — honours, and anything else that is just strings. */
export function TextList({
  label,
  items,
  onChange,
  placeholder,
}: {
  label: string
  items: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}) {
  return (
    <div className="f wide">
      <label>{label}</label>
      {items.map((text, i) => (
        <div className="bullet" key={i}>
          <input
            value={text}
            placeholder={placeholder}
            onChange={(e) => onChange(items.map((t, j) => (j === i ? e.target.value : t)))}
          />
          <button type="button" className="x" onClick={() => onChange(items.filter((_, j) => j !== i))}>
            ×
          </button>
        </div>
      ))}
      <button type="button" className="btn ghost sm" onClick={() => onChange([...items, ''])}>
        + add
      </button>
    </div>
  )
}

/** The save row. Hidden until something changed, so a page of cards is quiet. */
export function SaveBar({
  dirty,
  busy,
  error,
  onSave,
  onReset,
  children,
}: {
  dirty: boolean
  busy: boolean
  error: string | null
  onSave: () => void
  onReset?: () => void
  children?: ReactNode
}) {
  if (!dirty && !error) return children ? <div className="savebar">{children}</div> : null
  return (
    <div className="savebar">
      {dirty && (
        <>
          <button className="btn sm" onClick={onSave} disabled={busy}>
            {busy ? 'saving…' : 'Save'}
          </button>
          {onReset && (
            <button className="btn ghost sm" onClick={onReset} disabled={busy}>
              Undo
            </button>
          )}
        </>
      )}
      {children}
      {error && <div className="err">{error}</div>}
    </div>
  )
}

/** Runs a save, keeps the button honest about it, and turns a thrown error into
 * something a person can read. The server's refusals are written for the user —
 * "your legal name is locked, send unlock if it really changed" — so they are
 * shown as they arrive rather than replaced with "something went wrong". */
export function useSave(onDone?: () => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      onDone?.()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, save, clearError: () => setError(null) }
}

/** `''` is not a value. The server treats whitespace as "not stated" too, so this
 * keeps the two ends agreeing about what a cleared box means. */
export const orNull = (s: string): string | null => (s.trim() ? s.trim() : null)

export const text = (v: string | null | undefined): string => v ?? ''

/** Only the keys that changed. Everything on this page depends on it: a patch
 * carrying a field the user never touched tells the server they just set it. */
export function changedOnly<T extends Record<string, unknown>>(before: T, after: T): Partial<T> {
  const out: Partial<T> = {}
  for (const key of Object.keys(after) as (keyof T)[]) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) out[key] = after[key]
  }
  return out
}
