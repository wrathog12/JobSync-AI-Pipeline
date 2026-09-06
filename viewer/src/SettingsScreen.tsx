import { useState } from 'react'
import { api, type Health, type LlmConfig } from './api'
import { useSave } from './fields'

/** The short screen: what is switched on, where your data actually sits, and the
 * two buttons that throw it away.
 *
 * No API key box. Today the key lives in the server's own `.env`, and a field here
 * that pretended otherwise would be theatre — the page would be collecting a
 * credential it has nowhere to put. When per-user keys arrive this is where they
 * go, and `Bring your own key` below says so rather than leaving a gap.
 */
export function SettingsScreen({
  llm,
  health,
  onChange,
}: {
  llm: LlmConfig | null
  health: Health | null
  onChange: () => void
}) {
  const [confirming, setConfirming] = useState<'clear' | 'demo' | null>(null)
  const { busy, error, save } = useSave(() => {
    setConfirming(null)
    onChange()
  })
  const storage = health?.storage ?? null

  return (
    <>
      <section>
        <h2>Writing</h2>
        <div className="rec">
          {llm === null ? (
            <div className="hint">checking…</div>
          ) : llm.has_server_key ? (
            <>
              <p className="lead">
                Connected to {llm.provider}. Reading a résumé uses <code>{llm.model_fast}</code>;
                writing answers uses <code>{llm.model_strong}</code>.
              </p>
              <div className="hint">
                The key is in the server's own <code>.env</code> and never leaves it — this page has
                never seen it and there is no request that would return it.
              </div>
            </>
          ) : (
            <div className="hint warn">
              No API key on the server. Everything that does not need one still works — your profile,
              editing it, and the fields that are answered by looking a value up rather than writing
              prose. Reading a new résumé needs one. Put <code>GEMINI_API_KEY</code> in{' '}
              <code>server/.env</code> and restart it.
            </div>
          )}
        </div>
      </section>

      <section>
        <h2>Where your data is</h2>
        <div className="rec">
          {storage ? (
            <>
              <p className="lead">
                One file on this machine: <code>{storage.path}</code>. Nothing is uploaded anywhere.
              </p>
              <dl className="counts">
                <dt>history records</dt>
                <dd>{storage.ledger_record}</dd>
                <dt>skills</dt>
                <dd>{storage.declared_skill}</dd>
                <dt>documents you uploaded</dt>
                <dd>{storage.document}</dd>
                <dt>answers you approved</dt>
                <dd>{storage.approved_answer}</dd>
                <dt>applications in progress</dt>
                <dd>{storage.session}</dd>
              </dl>
              <div className="hint">
                Corrections show up here as extra records rather than replacements. An edit keeps the
                old version, flagged and out of use — if you have already sent an application built
                on it, that is the only thing that can still tell you what you said.
              </div>
            </>
          ) : (
            <div className="hint warn">
              Storage is switched off, so everything you save disappears when the server restarts. Set
              <code> JOBSYNC_DB_PATH</code> in <code>server/.env</code> to turn it on.
            </div>
          )}
        </div>
      </section>

      <section>
        <h2>Bring your own key</h2>
        <div className="rec">
          <p className="lead">
            Not built yet, on purpose. This is a single-user setup: one key, in the server's{' '}
            <code>.env</code>, and no accounts. Per-user keys mean per-user everything — accounts,
            a real database, and a place to keep a secret that is not a file on one laptop.
          </p>
        </div>
      </section>

      <section>
        <h2>Start over</h2>
        <div className="rec">
          {confirming === 'clear' ? (
            <>
              <p className="lead warn">
                This erases your name, your contact details, every job, every bullet and every skill.
                It cannot be undone and there is no backup.
              </p>
              <div className="savebar">
                <button className="btn danger" disabled={busy} onClick={() => save(api.clearMemory)}>
                  {busy ? 'erasing…' : 'Erase everything'}
                </button>
                <button className="btn ghost sm" disabled={busy} onClick={() => setConfirming(null)}>
                  Cancel
                </button>
              </div>
            </>
          ) : confirming === 'demo' ? (
            <>
              <p className="lead warn">
                The demo profile replaces yours — a made-up person with a locked name, which then gets
                in the way of your own. Only useful on an empty setup.
              </p>
              <div className="savebar">
                <button className="btn danger" disabled={busy} onClick={() => save(api.loadDemo)}>
                  {busy ? 'loading…' : 'Replace mine with the demo'}
                </button>
                <button className="btn ghost sm" disabled={busy} onClick={() => setConfirming(null)}>
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <div className="savebar">
              <button className="btn ghost sm" onClick={() => setConfirming('clear')}>
                Erase everything
              </button>
              <button className="btn ghost sm" onClick={() => setConfirming('demo')}>
                Load the demo profile
              </button>
            </div>
          )}
          {error && <div className="err">{error}</div>}
        </div>
      </section>
    </>
  )
}
