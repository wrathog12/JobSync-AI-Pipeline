import { useCallback, useEffect, useState } from 'react'
import { api, type Health, type LlmConfig, type MemoryView } from './api'
import { ProfileScreen } from './ProfileScreen'
import { SettingsScreen } from './SettingsScreen'
import { UploadScreen } from './UploadScreen'

/** JobSync — your profile.
 *
 * Three screens, because there are three things to do: get your history in, look
 * at it and fix it, and see what is switched on. This replaces a seven-tab trace
 * viewer that was built to debug retrieval — chunk scores, stage timings, mode
 * comparisons. All of that answers "why did the pipeline do that", which is a
 * question about the software. This page answers "is this right about me", which
 * is the only question its user has.
 */

type Screen = 'upload' | 'profile' | 'settings'

const NAV: { id: Screen; label: string }[] = [
  { id: 'upload', label: 'Add' },
  { id: 'profile', label: 'Profile' },
  { id: 'settings', label: 'Settings' },
]

export default function App() {
  const [screen, setScreen] = useState<Screen>('profile')
  const [memory, setMemory] = useState<MemoryView | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [llm, setLlm] = useState<LlmConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  /** Memory and health move together. An edit rebuilds the derived layers and
   * writes to disk, so a screen showing the new wording next to the old on-disk
   * count is how you spend an evening debugging a save that worked. */
  const reload = useCallback(async () => {
    try {
      const [mem, h] = await Promise.all([api.memory(), api.health()])
      setMemory(mem)
      setHealth(h)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    reload()
    api.llm().then(setLlm).catch(() => setLlm(null))
  }, [reload])

  // Land on Add when there is nothing to look at yet, rather than on an empty
  // Profile with a sentence telling them to go somewhere else.
  useEffect(() => {
    if (memory?.is_empty) setScreen('upload')
  }, [memory?.is_empty])

  const name =
    memory?.identity?.preferred_name ||
    [memory?.identity?.legal_first, memory?.identity?.legal_last].filter(Boolean).join(' ')

  return (
    <div className="app">
      <header>
        <div className="brand">
          <strong>JobSync</strong>
          {name && <span className="who">{name}</span>}
        </div>
        <nav>
          {NAV.map((n) => (
            <button key={n.id} data-active={screen === n.id} onClick={() => setScreen(n.id)}>
              {n.label}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div className="err banner">
          {error}
          <button className="btn ghost sm" onClick={reload}>
            Try again
          </button>
        </div>
      )}

      {health?.storage === null && (
        <div className="err banner warn">
          Storage is off, so nothing you save here survives a restart of the server.
        </div>
      )}

      <main>
        {screen === 'upload' && (
          <UploadScreen
            onSaved={async () => {
              await reload()
              setScreen('profile')
            }}
          />
        )}

        {screen === 'profile' &&
          (memory ? (
            <ProfileScreen memory={memory} onChange={reload} />
          ) : (
            <div className="empty big">loading…</div>
          ))}

        {screen === 'settings' && (
          <SettingsScreen llm={llm} health={health} onChange={reload} />
        )}
      </main>

      <footer>
        Everything on this page is on your own machine. Nothing is sent anywhere except the text of
        a résumé you upload, which goes to the model that reads it.
      </footer>
    </div>
  )
}
