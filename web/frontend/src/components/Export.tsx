import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { bytes, dur } from '../format'
import { renderSchedule, type Part } from '../overlayDraw'
import type { BoardStyle, ExportJob, ExportRecord, Overlays, TimelineData } from '../types'
import { ago } from '../ui'
import { SharePanel } from './SharePanel'

type Phase = { kind: 'ready' } | { kind: 'drawing'; done: number; of: number } | { kind: 'rendering'; job: ExportJob }
  | { kind: 'done'; job: ExportJob } | { kind: 'error'; message: string }

// Export: the edit, its words on screen and its music, as one file. The
// words are drawn here, by the same code as the preview, then composited
// by the server -- so the file shows exactly what the player showed.
// Past exports of this project are listed underneath (they're on the project).
export function Export({ tl, overlays, parts, music, credit, style, history = [], onClose }: {
  tl: TimelineData
  overlays: Overlays
  parts: Part[]
  music: string | null
  credit?: string | null     // the track's licence line, copied with the caption
  style?: BoardStyle | null
  history?: ExportRecord[]
  onClose: () => void
}) {
  const [phase, setPhase] = useState<Phase>({ kind: 'ready' })
  const [withMusic, setWithMusic] = useState(!!music)
  const [withWords, setWithWords] = useState(overlays.items.length > 0)
  const cancelled = useRef(false)
  const jobId = useRef<string | null>(null)
  const frame = tl.frame ?? { w: 1920, h: 1080 }
  const issues = overlays.findings.filter((f) => f.verdict === 'bad').length
  const busy = phase.kind === 'drawing' || phase.kind === 'rendering'

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [busy, onClose])

  // Versions made in this sitting before the one shown (the Share box's
  // "make a vertical version too" starts another from the same edit).
  const [made, setMade] = useState<ExportJob[]>([])
  // the export's place in the project's list, for "would you post this?"
  const base = useRef(history.length)

  const go = async (other?: 'tall' | 'wide') => {
    cancelled.current = false
    if (phase.kind === 'done') setMade((m) => [...m, phase.job])
    try {
      const job = await api.exportCreate(withMusic, other)
      jobId.current = job.id
      let schedule: { frame: number | null; start: number; end: number }[] = []
      if (withWords && overlays.items.length) {
        setPhase({ kind: 'drawing', done: 0, of: 1 })
        schedule = await renderSchedule({
          items: overlays.items, style: overlays.style, parts, fps: tl.fps, total: job.total, w: job.size.w, h: job.size.h,
          upload: async (n, png) => { await api.exportFrame(job.id, n, png) },
          onProgress: (done, of) => setPhase({ kind: 'drawing', done, of }),
          cancelled: () => cancelled.current,
        })
      }
      let s = await api.exportStart(job.id, schedule)
      setPhase({ kind: 'rendering', job: s })
      while (s.stage !== 'done' && s.stage !== 'error' && s.stage !== 'cancelled') {
        await new Promise((r) => setTimeout(r, 400))
        s = await api.exportStatus(job.id)
        setPhase({ kind: 'rendering', job: s })
      }
      if (s.stage === 'done') setPhase({ kind: 'done', job: s })
      else if (s.stage === 'error') setPhase({ kind: 'error', message: s.error ?? 'The export failed.' })
      else setPhase({ kind: 'ready' })
    } catch (e) {
      if (cancelled.current) { setPhase({ kind: 'ready' }); return }
      setPhase({ kind: 'error', message: (e as Error).message })
    }
  }

  const cancel = async () => {
    cancelled.current = true
    if (jobId.current) await api.exportCancel(jobId.current).catch(() => {})
  }

  const [verdict, setVerdict] = useState<null | 'sending' | 'sent'>(null)
  const [note, setNote] = useState('')
  // The caption to paste: the title line, and the music credit its licence asks for
  const title = overlays.items.find((o) => o.kind === 'title')?.text ?? ''
  const caption = [title, credit && phase.kind === 'done' && phase.job.music ? `Music: ${credit}` : ''].filter(Boolean).join('\n')
  const pct = phase.kind === 'drawing' ? phase.done / Math.max(1, phase.of)
    : phase.kind === 'rendering' ? phase.job.progress : phase.kind === 'done' ? 1 : 0
  const status = phase.kind === 'drawing' ? `Drawing the captions… ${phase.done}/${phase.of} frames`
    : phase.kind === 'rendering' ? ({
      waiting: 'Starting…', shots: `Rendering shots… ${phase.job.done} of ${phase.job.of}`, joining: 'Joining the shots…',
      finishing: `Adding ${phase.job.overlays ? 'words' : ''}${phase.job.overlays && phase.job.music ? ' and ' : ''}${phase.job.music ? 'music' : ''}${!phase.job.overlays && !phase.job.music ? 'sound' : ''}… ${Math.round(phase.job.progress * 100)}%`,
      done: 'Done', error: 'Failed', cancelled: 'Cancelled',
    } as const)[phase.job.stage] : ''

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-[2px]" onPointerDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div role="dialog" aria-labelledby="export-title" className="max-h-[92vh] w-[460px] max-w-[92vw] overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-2xl shadow-black/60">
        <div className="flex items-baseline gap-2">
          <h2 id="export-title" className="font-serif text-[24px] text-zinc-100">Export</h2>
          <span className="text-[12px] text-muted">{phase.kind === 'done' ? `${phase.job.size.w}×${phase.job.size.h}` : `${frame.w}×${frame.h}`} · {dur(tl.total)} · 30 fps</span>
        </div>
        <p className="mt-1 text-[12px] leading-snug text-zinc-400">
          Renders the timeline to one MP4 in <span className="text-zinc-300">Movies/VibeCut</span>. Your original clips are only read.
          {frame.h > frame.w ? ' Vertical, because most of this edit was filmed that way.' : ''}
        </p>

        <div className="mt-4 space-y-2 text-[12px]">
          <Toggle on={withWords} disabled={!overlays.items.length || busy} onChange={setWithWords}
                  label={overlays.items.length ? `Captions (${overlays.items.length})` : 'Captions — none yet'} />
          <Toggle on={withMusic} disabled={!music || busy} onChange={setWithMusic}
                  label={music ? `Music: ${music}` : 'Music — none chosen under the edit'} />
          {style && (style.look || style.transitions || style.letterbox) && (
            <p className="rounded-lg bg-raised px-2.5 py-1.5 text-[11px] leading-snug text-zinc-300">
              {style.ref ? `Borrowed from “${style.name}”` : `The ${style.name} look`}: {[style.look && 'its colour', style.transitions && (style.transitions.between !== 'cut' || style.transitions.open || style.transitions.close) && 'its transitions',
                style.letterbox && 'cinematic bars'].filter(Boolean).join(', ') || 'its timing'} — rendered here, not in the preview.
            </p>
          )}
          {withWords && issues > 0 && (
            <p className="rounded-lg bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-200">
              {issues} overlay{issues === 1 ? ' has' : 's have'} a problem a viewer would notice (cut off, too quick to read, or overlapping). They’re marked in Captions.
            </p>
          )}
        </div>

        {phase.kind !== 'ready' && (
          <div className="mt-4">
            <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
              <div className={`h-full rounded-full ${phase.kind === 'error' ? 'bg-rose-400' : 'bg-accent'} transition-[width] duration-300`} style={{ width: `${pct * 100}%` }} />
            </div>
            {status && <p className="mt-1.5 text-[11px] tabular-nums text-muted">{status}</p>}
            {phase.kind === 'error' && <p className="mt-1.5 text-[12px] text-rose-300">{phase.message}</p>}
            {phase.kind === 'done' && (
              <p className="mt-1.5 text-[12px] text-zinc-200">Saved <span className="font-medium">{phase.job.file}</span>
                {phase.job.alt ? ` (${phase.job.size.h > phase.job.size.w ? 'vertical' : 'wide'} version)` : ''} in {phase.job.elapsed.toFixed(0)}s.
                {phase.job.notes?.length ? <span className="block text-muted">{phase.job.notes.join(' ')}</span> : null}</p>
            )}
            {phase.kind === 'done' && made.length > 0 && (
              <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted">
                {made.map((m) => (
                  <li key={m.id} className="flex gap-2"><span className="min-w-0 flex-1 truncate">Also made just now: {m.file}</span>
                    <a href={`/api/export/${m.id}/file`} download className="shrink-0 text-accent hover:underline">Download</a></li>
                ))}
              </ul>
            )}
            {phase.kind === 'done' && <SharePanel job={phase.job} caption={caption} onOther={(f) => go(f)} />}
            {phase.kind === 'done' && !phase.job.alt && (
              // The one question that is the launch metric: would you post this?
              <div className="mt-3 rounded-lg border border-line px-2.5 py-2">
                {verdict === 'sent' ? <p className="text-[12px] text-zinc-300">Noted — thank you.</p> : <>
                  <p className="font-serif text-[14px] text-zinc-100">Would you post this?</p>
                  <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="One line on what's wrong or right (optional)"
                         className="mt-1.5 w-full rounded-md border border-line bg-panel px-2 py-1 text-[12px] text-zinc-100 outline-none focus:border-zinc-500" />
                  <div className="mt-1.5 flex gap-1.5">
                    {([['yes', 'Yes, as it is'], ['no', 'Not yet']] as const).map(([k, label]) => (
                      <button key={k} type="button" disabled={verdict === 'sending'}
                              onClick={async () => {
                                setVerdict('sending')
                                try { await api.exportVerdict(base.current + made.length, k === 'yes', note); setVerdict('sent') }
                                catch { setVerdict(null) }
                              }}
                              className={`rounded-md px-2.5 py-1 text-[12px] ${k === 'yes' ? 'bg-accent font-semibold text-accent-ink' : 'border border-line text-zinc-200 hover:bg-raised'}`}>{label}</button>
                    ))}
                  </div>
                </>}
              </div>
            )}
          </div>
        )}

        {history.length > 0 && phase.kind !== 'done' && (
          <div className="mt-4 border-t border-line pt-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">Exported before</div>
            <ul className="mt-1.5 max-h-32 space-y-1 overflow-y-auto text-[12px]">
              {[...history].reverse().map((h, k) => (
                <li key={h.job} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-zinc-300" title={h.path}>{h.file}</span>
                  <span className="shrink-0 text-[11px] tabular-nums text-muted">{dur(h.seconds)}{h.bytes ? ` · ${bytes(h.bytes)}` : ''} · {ago(h.at)}</span>
                  <a href={`/api/exports/${history.length - 1 - k}/file`} download className="shrink-0 text-[11px] text-accent hover:underline">Download</a>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          {phase.kind === 'done' ? <>
            <button type="button" onClick={onClose} className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-semibold text-accent-ink">Done</button>
          </> : busy ? (
            <button type="button" onClick={cancel} className="rounded-lg border border-line px-3 py-1.5 text-[12px] text-zinc-200 hover:bg-raised">Cancel</button>
          ) : <>
            <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-[12px] text-muted hover:text-zinc-200">Close</button>
            <button type="button" onClick={() => go()} disabled={!tl.items.length} className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-semibold text-accent-ink disabled:opacity-30">
              {phase.kind === 'error' ? 'Try again' : 'Export video'}
            </button>
          </>}
        </div>
      </div>
    </div>
  )
}

function Toggle({ on, disabled, onChange, label }: { on: boolean; disabled?: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className={`flex items-center gap-2 ${disabled ? 'text-zinc-600' : 'text-zinc-200'}`}>
      <input type="checkbox" checked={on && !disabled} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="accent-[#1f5f8b]" />
      <span className="truncate">{label}</span>
    </label>
  )
}
