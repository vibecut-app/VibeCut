import { useEffect, useRef, useState } from 'react'
import type { Board, Session } from '../types'
import { dur } from '../format'

type Suggestion = { id: string; title: string; duration: number; bpm: number | null; score: number; reason: string; audio: string }
type MusicState = {
  folder: string | null; status: 'none' | 'indexing' | 'ready' | 'error'; done: number; total: number
  error: string | null; tracks: number; unreadable: number
  edit_seconds?: number; too_short?: number; flat?: boolean; suggestions?: Suggestion[]
}

// Tracks from the creator's own folder whose energy follows the storyboard's
// shape. Recomputed whenever the storyboard changes; nothing is placed.
// `folderOnly`: a song is already under the video, and the folder's songs are
// in "Songs that fit" (SongPicker) with everything else, so only the folder shows.
export function Music({ board, inUse, onSession, folderOnly = false }: {
  board: Board; inUse: string | null; onSession: (s: Session) => void; folderOnly?: boolean
}) {
  const [m, setM] = useState<MusicState | null>(null)
  const [editing, setEditing] = useState(false)
  const [folder, setFolder] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const key = JSON.stringify(board.beats.map((b) => [b.id, b.shots.map((s) => [s.id, s.start, s.end])]))

  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      const r: MusicState = await (await fetch('/api/music/suggest')).json()
      if (stop) return
      setM(r)
      if (r.status === 'indexing') timer = window.setTimeout(load, 800)
    }
    load()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [key])

  const save = async () => {
    setErr(null)
    const r = await fetch('/api/music/folder', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ folder }),
    })
    if (!r.ok) { setErr((await r.json()).detail); return }
    setEditing(false)
    setM(await r.json())
    // poll through indexing
    const poll = async () => {
      const s: MusicState = await (await fetch('/api/music/suggest')).json()
      setM(s)
      if (s.status === 'indexing') setTimeout(poll, 800)
    }
    poll()
  }

  // Put a track under the edit: its beat grid becomes snap targets and it
  // plays along with the timeline. Nothing is placed or trimmed.
  const use = async (id: string | null) => {
    const r = await fetch('/api/music/use', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ track_id: id }),
    })
    if (r.ok) onSession(await r.json())
  }

  const play = (s: Suggestion) => {
    const el = audio.current
    if (!el) return
    if (playing === s.id) { el.pause(); setPlaying(null); return }
    el.src = s.audio
    el.play().catch(() => {})
    setPlaying(s.id)
  }

  if (!m) return null
  if (m.status === 'none' && !editing) {
    return (
      <button type="button" onClick={() => setEditing(true)}
              className="rounded-xl border border-dashed border-line px-3 py-2.5 text-left text-[12px] text-muted hover:text-zinc-200">
        ♪ Find music from your own folder that fits this story…
      </button>
    )
  }
  const showField = editing || m.status === 'none'
  if (folderOnly && !showField && m.status === 'ready' && m.folder) {
    return (
      <p className="text-[11px] text-muted">
        Your music folder ({m.tracks} songs) is in the suggestions above.{' '}
        <button type="button" onClick={() => { setFolder(m.folder ?? ''); setEditing(true) }} className="underline hover:text-zinc-300">
          Change folder
        </button>
      </p>
    )
  }

  return (
    <section className="rounded-xl border border-line bg-raised px-3 py-2.5">
      <audio ref={audio} onEnded={() => setPlaying(null)} />
      <div className="flex items-baseline gap-2">
        <h4 className="font-serif text-[15px] text-zinc-100">Music that fits this shape</h4>
        {m.folder && !showField && (
          <button type="button" onClick={() => { setFolder(m.folder ?? ''); setEditing(true) }}
                  className="ml-auto truncate text-[10px] text-muted hover:text-zinc-300" title={m.folder}>
            {m.folder.split('/').slice(-2).join('/')} · change
          </button>
        )}
      </div>

      {showField && (
        <div className="mt-2">
          <div className="flex gap-1.5">
            <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="~/Music/Vlog"
                   onKeyDown={(e) => { if (e.key === 'Enter') save() }}
                   className="min-w-0 flex-1 rounded-md border border-line bg-panel px-2 py-1 text-[12px] text-zinc-100 outline-none focus:border-zinc-500" />
            <button type="button" onClick={save} disabled={!folder.trim()}
                    className="rounded-md bg-accent px-2.5 text-[12px] font-semibold text-accent-ink disabled:opacity-30">Set</button>
          </div>
          <p className="mt-1 text-[10px] text-muted">Your own music folder — mp3, m4a, wav, flac. Read on this Mac only.</p>
          {err && <p className="mt-1 text-[11px] text-rose-300">{err}</p>}
        </div>
      )}

      {m.status === 'indexing' && (
        <p className="mt-2 text-[11px] text-muted">Reading tracks… {m.done}/{m.total || '?'} (first time only)</p>
      )}
      {m.status === 'error' && <p className="mt-2 text-[11px] text-rose-300">{m.error}</p>}

      {m.status === 'ready' && !showField && (() => {
        if (m.tracks === 0) return <p className="mt-2 text-[11px] text-muted">No mp3, m4a, wav or flac files in that folder.</p>
        if (m.flat) return <p className="mt-2 text-[11px] text-muted">This storyboard has one energy level throughout, so there's no shape to match a track to.</p>
        const list = m.suggestions ?? []
        if (!list.length) return (
          <p className="mt-2 text-[11px] text-muted">
            None of your {m.tracks} tracks is as long as this edit ({dur(m.edit_seconds ?? 0)}). Tighten it, or add longer tracks.
          </p>
        )
        return (
          <ol className="mt-2 space-y-2">
            {list.map((s, i) => (
              <li key={s.id} className="flex gap-2">
                <button type="button" onClick={() => play(s)} title={playing === s.id ? 'Stop' : 'Play'}
                        className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-zinc-800 text-zinc-100 hover:bg-zinc-700">
                  {playing === s.id ? <span className="block size-2 bg-current" />
                    : <span className="ml-0.5 block size-0 border-y-[4px] border-l-[7px] border-y-transparent border-l-current" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] text-zinc-200">{i + 1}. {s.title}</span>
                    <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted">
                      {dur(s.duration)}{s.bpm ? ` · ${s.bpm} BPM` : ''}
                    </span>
                    <button type="button" onClick={() => use(inUse === s.id ? null : s.id)}
                            title={inUse === s.id ? 'Take it out from under the edit'
                              : s.bpm ? 'Use under the edit — its beats become snap targets' : 'Use under the edit (no steady tempo, so no beat grid)'}
                            className={`shrink-0 rounded px-1.5 py-px text-[10px] ${inUse === s.id ? 'bg-accent text-accent-ink' : 'border border-line text-muted hover:text-zinc-200'}`}>
                      {inUse === s.id ? 'In use' : 'Use'}
                    </button>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="h-1 w-12 shrink-0 overflow-hidden rounded-full bg-zinc-800" title={`shape correlation ${s.score.toFixed(2)}`}>
                      <span className="block h-full bg-accent" style={{ width: `${Math.max(0, s.score) * 100}%` }} />
                    </span>
                    <span className="text-[11px] leading-snug text-zinc-400">
                      {s.reason || (s.score < 0.3 ? 'Weak match — the shapes barely agree.' : '')}
                    </span>
                  </div>
                </div>
              </li>
            ))}
            {(m.too_short ?? 0) > 0 && (
              <li className="text-[10px] text-muted">{m.too_short} of {m.tracks} tracks are shorter than this edit ({dur(m.edit_seconds ?? 0)}) and were left out.</li>
            )}
          </ol>
        )
      })()}
    </section>
  )
}
