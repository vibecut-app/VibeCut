import { useState } from 'react'
import { api } from '../api'
import type { CutNote, CutReport } from '../types'

// Check my cut: the checks every turn already runs, as a list an editor
// friend would give -- in order, with the time, what's off and what
// usually helps. Report only: a note jumps the preview there, it never
// changes the edit (backend cutnotes.py).

export function CutNotes({ turn, onJump }: { turn: number | null; onJump: (n: CutNote) => void }) {
  const [rep, setRep] = useState<CutReport | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [at, setAt] = useState<number | null>(null)

  const check = async () => {
    setBusy(true); setError(null)
    try { setRep(await api.cutNotes()); setOpen(true); setAt(null) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const stale = !!rep && rep.turn !== turn

  return (
    <div>
      <button type="button" onClick={() => (rep && open && !stale ? setOpen(false) : check())} disabled={busy}
              title="Notes on your edit, moment by moment: where it may read as amateur, and what usually helps. Changes nothing."
              className="w-full rounded-lg border border-line px-3 py-2 text-left font-serif text-[16px] text-zinc-100 hover:bg-raised disabled:opacity-50">
        {busy ? 'Checking…' : 'Check my cut'}
        {rep && !busy && rep.notes.length > 0 && <span className="ml-1.5 rounded bg-amber-300/15 px-1 align-middle font-sans text-[10px] text-amber-200">{rep.notes.length}</span>}
      </button>
      {error && <p className="mt-1.5 text-[11px] text-amber-200">{error}</p>}
      {rep && open && (
        <div className="mt-2 rounded-lg border border-line bg-panel p-2.5 text-[12px]">
          <p className="leading-snug text-zinc-200">{rep.headline}</p>
          {stale && <button type="button" onClick={check} className="mt-1 text-[11px] text-accent hover:underline">
            You’ve changed the edit since — check again</button>}
          {rep.notes.length > 0 && <ol className="mt-2 space-y-1">
            {rep.notes.map((n, i) => (
              <li key={`${n.kind}-${n.after ?? n.overlay}-${i}`}>
                <button type="button" onClick={() => { setAt(i); onJump(n) }} aria-pressed={at === i}
                        title={n.kind === 'cut' ? 'Play through this cut' : 'Show this caption'}
                        className={`flex w-full gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-raised ${at === i ? 'bg-raised' : ''}`}>
                  <span className={`mt-px shrink-0 self-start rounded px-1 font-mono text-[11px] tabular-nums ${n.verdict === 'bad' ? 'bg-rose-400/15 text-rose-200' : 'bg-amber-300/15 text-amber-200'}`}>{n.at}</span>
                  <span className="min-w-0">
                    <span className="block text-zinc-100">{n.title}</span>
                    {n.lines.map((l) => <span key={l} className="mt-0.5 block leading-snug text-zinc-300">{l}</span>)}
                    {n.helps.map((h) => <span key={h} className="mt-0.5 block text-[11px] leading-snug text-muted">Usually helps: {h}</span>)}
                  </span>
                </button>
              </li>
            ))}
          </ol>}
          {rep.unchecked.length > 0 && <div className="mt-2 border-t border-line pt-1.5 text-[11px] text-muted">
            {rep.unchecked.map((u) => <p key={u}>{u}</p>)}
          </div>}
          <p className="mt-1.5 text-[11px] leading-snug text-zinc-500">{rep.priors}</p>
        </div>
      )}
    </div>
  )
}
