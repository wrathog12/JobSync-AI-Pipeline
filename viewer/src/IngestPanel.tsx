import { useRef, useState } from 'react'
import { api } from './api'
import type { DocumentView } from './types.generated'

/** Ingest readout — the extracted text, shown verbatim.
 *
 * Showing the raw text is the whole point of this panel. A column-scrambling bug
 * is obvious here and invisible two steps later, once an LLM has turned the
 * scrambled lines into a tidy employment record with the wrong dates on it.
 */
export function IngestPanel({
  doc,
  onExtract,
}: {
  doc: DocumentView | null
  onExtract: (d: DocumentView) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [pasted, setPasted] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<DocumentView>) => {
    setBusy(true)
    setError(null)
    try {
      onExtract(await fn())
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const blocking = doc?.warnings.filter((w) => w.blocking) ?? []
  const advisories = doc?.warnings.filter((w) => !w.blocking) ?? []

  return (
    <div className="mem">
      <div className="card">
        <h3>Upload a résumé</h3>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          style={{ width: '100%', marginBottom: 10 }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) run(() => api.upload(f))
          }}
        />
        <div className="src">
          PDF, Word, or plain text. The format is detected from the file's contents, so a
          mislabelled extension is fine.
        </div>

        <h3 style={{ marginTop: 18 }}>…or paste it</h3>
        <textarea
          rows={5}
          value={pasted}
          placeholder="Paste your résumé text here. Always works — no layout or font risk."
          onChange={(e) => setPasted(e.target.value)}
        />
        <button
          className="btn"
          style={{ marginTop: 8 }}
          disabled={busy || !pasted.trim()}
          onClick={() => run(() => api.paste(pasted))}
        >
          {busy ? 'extracting…' : 'Extract from pasted text'}
        </button>
        {error && <div className="err">{error}</div>}
      </div>

      {doc && (
        <div className="card">
          <h3>Extraction</h3>
          <dl className="kv">
            <dt>id</dt>
            <dd>{doc.doc_id}</dd>
            <dt>file</dt>
            <dd>{doc.filename ?? '(pasted)'}</dd>
            <dt>format</dt>
            <dd>{doc.kind}</dd>
            <dt>layout</dt>
            <dd>
              {doc.layout === 'multi_column' ? (
                <span className="pill gap">{doc.layout}</span>
              ) : (
                <span className="pill thin">{doc.layout}</span>
              )}
            </dd>
            <dt>pages</dt>
            <dd>{doc.page_count || '—'}</dd>
            <dt>size</dt>
            <dd>
              {doc.char_count.toLocaleString()} chars · {doc.word_count.toLocaleString()} words ·{' '}
              {doc.line_count} lines
            </dd>
            <dt>usable</dt>
            <dd>
              {doc.is_usable ? (
                <span className="pill thin">yes — ready to structure</span>
              ) : (
                <span className="pill gap">no — blocked</span>
              )}
            </dd>
          </dl>
        </div>
      )}

      {doc && (blocking.length > 0 || advisories.length > 0) && (
        <div className="card wide">
          <h3>Warnings</h3>
          {blocking.map((w, i) => (
            <div className="violation" key={`b${i}`}>
              ✗ <strong>{w.code}</strong> — {w.message}
            </div>
          ))}
          {advisories.map((w, i) => (
            <div className="stretchrow" key={`a${i}`}>
              ⚠ {w.code}
              <div className="note">{w.message}</div>
            </div>
          ))}
        </div>
      )}

      {doc && (
        <div className="card wide">
          <h3>Extracted text — read this before confirming anything</h3>
          {doc.text ? (
            <pre className="prompt" style={{ maxHeight: 460, overflow: 'auto' }}>
              {doc.text}
            </pre>
          ) : (
            <div className="empty">Nothing was extracted.</div>
          )}
        </div>
      )}

      {!doc && (
        <div className="card wide">
          <div className="empty">
            No document yet. Upload or paste one — the next step (structuring into L0/L1/L2
            candidates) reads from here.
          </div>
        </div>
      )}
    </div>
  )
}
