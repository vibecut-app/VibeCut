import { useEffect, useRef, useState } from 'react'
import { api, type Song, type SongOptions } from '../api'
import type { Session } from '../types'
import { Button } from '../ui'

// The Music panel's three tools (2026-10-24): songs that fit to listen to
// and swap, VibeCut's own transition sounds, and a trending sound to cut to
// (it plays here; the export goes out without it, and the creator adds the
// same sound in the app when posting).
export function SongPicker({ session, onSession, note }: {
  session: Session; onSession: (s: Session, undoable?: boolean) => void; note: (m: string) => void
}) {
  const [o, setO] = useState<SongOptions | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  const [source, setSource] = useState('')
  const [trend, setTrend] = useState<{ id: string; stage: string; error: string | null } | null>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const current = session.music?.id ?? null
  const guide = !!session.music?.guide

  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const r = await api.songs()
        if (stop) return
        setO(r)
        if (r.status === 'looking') timer = window.setTimeout(load, 1500)
      } catch { /* the panel stays as it was */ }
    }
    load()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [current, session.board?.option])

  const play = (s: Song) => {
    const el = audio.current
    if (!el) return
    if (playing === s.id) { el.pause(); setPlaying(null); return }
    el.src = s.audio
    // start where it would sit under the video, so what's heard is what it'd be
    el.currentTime = s.in
    el.play().catch(() => {})
    setPlaying(s.id)
  }

  const swap = async (s: Song) => {
    setBusy(s.id)
    audio.current?.pause(); setPlaying(null)
    try { onSession(await api.swapSong(s.id), true) } catch (e) { note((e as Error).message) } finally { setBusy(null) }
  }

  const sounds = async (on: boolean) => {
    setBusy('sfx')
    try { onSession(await api.sfx(on), true) } catch (e) { note((e as Error).message) } finally { setBusy(null) }
  }

  const cutTo = async () => {
    if (!source.trim()) return
    try {
      let j = await api.trend(source.trim())
      setTrend(j)
      while (j.stage !== 'done' && j.stage !== 'error') {
        await new Promise((r) => setTimeout(r, 1000))
        const s = await api.trendStatus(j.id)
        j = s
        setTrend(s)
        if (s.session) onSession(s.session, s.stage === 'done')
      }
      if (j.stage === 'done') setSource('')
    } catch (e) { note((e as Error).message) }
  }

  if (!session.board) return null
  const list = o?.songs ?? []
  const sfxOn = (session.music?.sfx ?? 0) > 0
  const m = session.music

  return (
    <div className="space-y-5">
      <audio ref={audio} onEnded={() => setPlaying(null)} />

      {guide && m && (
        <section className="rounded-xl border border-accent/40 bg-raised px-3 py-2.5">
          <h4 className="font-serif text-[15px] text-zinc-100">Cut to a trending sound</h4>
          <p className="mt-1 text-[12px] leading-snug text-zinc-300 [overflow-wrap:anywhere]">
            The cuts are on the beat of <b className="font-medium">{m.title}</b>. It plays here so you can cut by ear.
            When you post, add the same sound in TikTok or Instagram, starting at <b className="font-medium tabular-nums">{clock(m.start_at ?? 0)}</b>.
          </p>
          <p className="mt-1 text-[11px] text-muted">It isn't in the exported file: trending sounds are licensed for use inside those apps.</p>
        </section>
      )}

      {m && (
        <section>
          <div className="flex items-baseline gap-2">
            <h4 className="font-serif text-[15px] text-zinc-100">Songs that fit</h4>
            {o?.status === 'ready' && list.length > 1 && (
              <span className="ml-auto text-[10px] text-muted">{o.rebuilds ? 'Picking one makes the video again on its beat' : 'Your cuts stay where they are'}</span>
            )}
          </div>
          {o?.status === 'looking' && <p className="mt-1.5 text-[11px] text-muted">Looking for songs that fit…</p>}
          {o?.status !== 'looking' && !list.length && (
            <p className="mt-1.5 text-[11px] text-muted">{o?.why ?? 'No other songs fit this edit yet.'}</p>
          )}
          <ol className="mt-2 space-y-2">
            {list.map((s) => (
              <li key={s.id} className="flex gap-2">
                <button type="button" onClick={() => play(s)} title={playing === s.id ? 'Stop' : 'Listen from where it would start'}
                        className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-zinc-800 text-zinc-100 hover:bg-zinc-700">
                  {playing === s.id ? <span className="block size-2 bg-current" />
                    : <span className="ml-0.5 block size-0 border-y-[4px] border-l-[7px] border-y-transparent border-l-current" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] text-zinc-200" title={s.title}>{s.title}</span>
                    {s.in_use
                      ? <span className="ml-auto shrink-0 rounded bg-accent px-1.5 py-px text-[10px] text-accent-ink">Playing</span>
                      : <button type="button" disabled={!!busy} onClick={() => swap(s)}
                                className="ml-auto shrink-0 rounded border border-line px-1.5 py-px text-[10px] text-muted hover:text-zinc-200 disabled:opacity-40">
                          {busy === s.id ? '…' : 'Use this'}
                        </button>}
                  </div>
                  <p className="mt-0.5 text-[11px] leading-snug text-zinc-400">{s.why}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {m && !guide && (
        <section className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h4 className="font-serif text-[15px] text-zinc-100">Transition sounds</h4>
            <p className="mt-0.5 text-[11px] leading-snug text-zinc-400">
              {sfxOn ? `On: ${session.music?.sfx} in this video. A whoosh where it swipes or zooms; on a short, a riser and a hit on the drop.`
                : 'A whoosh where the video swipes or zooms; on a short, a riser and a hit on the drop. VibeCut makes these sounds itself.'}
            </p>
          </div>
          <Button size="sm" aria-pressed={sfxOn} disabled={busy === 'sfx'} onClick={() => sounds(!sfxOn)}>
            {sfxOn ? 'Turn off' : 'Turn on'}
          </Button>
        </section>
      )}

      <section>
        <h4 className="font-serif text-[15px] text-zinc-100">{guide ? 'Another trending sound' : 'Cut to a trending sound'}</h4>
        <p className="mt-0.5 text-[11px] leading-snug text-zinc-400">
          {o?.can_link === false ? 'Pick the sound saved as a file' : 'Paste a TikTok, Reel or Short that uses the sound, or a saved file'}.
          The cuts go on its beat; you add the sound itself in the app when you post.
        </p>
        <div className="mt-2 flex gap-1.5">
          <input value={source} onChange={(e) => setSource(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') cutTo() }}
                 placeholder={o?.can_link === false ? '~/Music/sound.mp3' : 'https://www.tiktok.com/@…'}
                 className="min-w-0 flex-1 rounded-md border border-line bg-panel px-2 py-1 text-[12px] text-zinc-100 outline-none focus:border-zinc-500" />
          <Button size="sm" variant="primary" disabled={!source.trim() || (!!trend && trend.stage !== 'done' && trend.stage !== 'error')} onClick={cutTo}>
            Cut to it
          </Button>
        </div>
        {trend && trend.stage !== 'done' && (
          <p className={`mt-1 text-[11px] ${trend.stage === 'error' ? 'text-rose-300' : 'text-muted'}`}>
            {trend.stage === 'error' ? trend.error : trend.stage === 'fetching' ? 'Getting the sound…' : 'Finding its beat…'}
          </p>
        )}
        {o?.can_link === false && <p className="mt-1 text-[10px] text-muted">Links need yt-dlp on this Mac (brew install yt-dlp).</p>}
      </section>
    </div>
  )
}

function clock(s: number) {
  const t = Math.max(0, Math.round(s))
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
}
