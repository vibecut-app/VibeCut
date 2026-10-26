// "Which do you like better?" (backend prefer.py; sarah, 2026-10-21): after
// Make, a few cards, each two versions of the video that differ in one part
// (the opening, the rhythm, the order, the ending). Each version plays the
// same few seconds with the sound export would write. Her pick teaches her
// layer of the taste model and, while the video is as Make left it, puts the
// picked version on it as one undoable turn.
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { locate, toSource, type SeqItem } from '../sequence'
import { dress, transport, transportStore } from '../transport'
import type { PreferCard, PreferSide, Session, Turn } from '../types'
import { Button } from '../ui'

const DRIFT = 0.25      // seconds the picture may wander from the sound before it is put back
const H = 210           // a version's height on the card: big enough to judge, small enough that the video stays biggest

type Said = { deck: number; text: string; turn: number | null }

export function PreferCards({ prefer, turns, onSession }: {
  prefer: { at: number; of: number; deck: number; on: number | null } | null
  turns: Turn[]
  onSession: (s: Session) => void
}) {
  const [card, setCard] = useState<(PreferCard & { deck: number }) | null>(null)
  const [frame, setFrame] = useState<{ w: number; h: number } | null>(null)
  const [playing, setPlaying] = useState<{ card: string; i: number } | null>(null)   // per card: a new one never starts playing
  const [again, setAgain] = useState(0)        // a card that had gone: fetch the one there is now
  const [said, setSaid] = useState<Said | null>(null)
  const [finished, setFinished] = useState<Said | null>(null)    // the last answer, shown a moment after the last card
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hidden, setHidden] = useState<number | null>(null)   // "Not now": the deck it was said to

  const deck = prefer?.deck ?? null
  const at = prefer?.at ?? 0
  const on = prefer?.on ?? null       // the turn the video's version is read from: an Undo moves it, and the card is cut again
  useEffect(() => {
    if (deck === null || hidden === deck) return
    let live = true
    api.prefer()
      .then((r) => { if (live) { setCard(r.card && { ...r.card, deck }); setFrame(r.frame); setError('') } })
      .catch((e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [deck, at, on, hidden, again])

  const shown = card && deck !== null && card.deck === deck ? card : null
  if (deck !== null && hidden === deck) return null

  // what the last pick did, with its Undo when it changed the video
  const undo = async (turn: number) => {
    try {
      onSession(await api.toggle(turn))
      setSaid(null)
      setFinished(null)
    } catch (e) { setError((e as Error).message) }
  }
  // Undo only while that turn is in the video (the top bar's Undo may have taken it already: this would redo it)
  const saidLine = (x: Said) => (
    <p className="font-serif text-[16px] text-zinc-200">
      {x.text}{x.turn !== null && turns.some((t) => t.id === x.turn && !t.undone) &&
        <> · <button type="button" className="underline" onClick={() => undo(x.turn!)}>Undo</button></>}
    </p>
  )
  if (!shown) {
    return finished && deck === null ? <div className="mt-3 max-w-[1100px] text-center">{saidLine(finished)}</div>
      : error && deck !== null ? <p className="mt-3 text-[15px] text-rose-300">{error}</p> : null
  }

  const pick = async (i: number | null) => {
    setBusy(true)
    setPlaying(null)
    try {
      const r = await api.preferPick(shown.id, i)
      const x = { deck: shown.deck, text: r.prefer_said, turn: r.prefer_landed ? r.turns.at(-1)?.id ?? null : null }
      setSaid(x)
      setCard(null)
      if (!r.prefer) {
        setFinished({ ...x, text: `${x.text} Thanks, that's all for this video.` })
        window.setTimeout(() => setFinished(null), 12000)
      }
      onSession(r)
    } catch (e) {
      setError((e as Error).message)
      setAgain((n) => n + 1)
    } finally {
      setBusy(false)
    }
  }

  // a strip under the video, so the video stays the biggest thing: the question
  // and its answers on the left, the two versions side by side on the right
  const ratio = frame ? frame.w / frame.h : 9 / 16
  const key = `${shown.deck}-${shown.id}`
  return (
    <section aria-label="Which version do you like better?"
             className="mt-3 flex w-full max-w-[1100px] flex-col gap-3 rounded-2xl border border-line bg-panel px-4 py-3 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="font-serif text-[19px] leading-snug text-zinc-100">{shown.ask}</h3>
        <p className="text-[15px] text-zinc-300">Play both, then pick one. {shown.at} of {shown.of}; each pick teaches VibeCut your taste.</p>
        {said && said.deck === shown.deck && saidLine(said)}
        <div className="mt-1 flex flex-wrap gap-2">
          <Button variant="secondary" size="md" disabled={busy} onClick={() => pick(null)}>Can't tell</Button>
          <Button variant="ghost" size="md" disabled={busy} onClick={() => { setPlaying(null); setHidden(shown.deck) }}>Not now</Button>
        </div>
        {error && <p className="text-[15px] text-rose-300">{error}</p>}
      </div>
      <div className="flex justify-center gap-4">
        {shown.sides.map((s, i) => (
          <div key={`${key}-${i}`} className="flex flex-col items-center gap-2">
            <Version side={s} ratio={ratio} label={i ? 'B' : 'A'} playing={playing?.card === key && playing.i === i}
                     onPlay={() => { transport.stop(); setPlaying({ card: key, i }) }}
                     onStop={() => setPlaying((p) => (p?.card === key && p.i === i ? null : p))} />
            <Button variant="primary" size="md" disabled={busy} onClick={() => pick(i)}>This one</Button>
          </div>
        ))}
      </div>
    </section>
  )
}

/** One version: the window's shots in two <video>s (the next one parked on
 *  its first frame, so a cut is a swap) under the mixed sound, which keeps the time. */
function Version({ side, ratio, label, playing, onPlay, onStop }: {
  side: PreferSide; ratio: number; label: string; playing: boolean; onPlay: () => void; onStop: () => void
}) {
  const a = useRef<HTMLVideoElement>(null)
  const b = useRef<HTMLVideoElement>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const st = useRef({ front: 0, cur: -1, pre: -1, t0: 0, raf: 0 })
  const items = side.items as SeqItem[]

  const els = () => [a.current, b.current] as const
  const url = (it: SeqItem) => `/api/video/${it.clip_id}`
  const load = (v: HTMLVideoElement, it: SeqItem, t: number) => {
    if (it.kind !== 'shot' || !it.clip_id) return
    if (v.getAttribute('src') !== url(it)) v.src = url(it)
    const go = () => { v.currentTime = toSource(it, t) }
    if (v.readyState >= 1) go()
    else v.addEventListener('loadedmetadata', go, { once: true })
  }
  // where it rests: the window's first frame
  const rest = () => {
    const [f, bk] = els()
    const k = locate(items, side.start)
    st.current = { ...st.current, front: 0, cur: -1, pre: -1 }
    if (f && k >= 0) { load(f, items[k], side.start); f.pause(); f.style.opacity = '1'; dress(f, items[k], false) }
    if (bk) { bk.pause(); bk.style.opacity = '0' }
  }
  useEffect(rest, [side]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const s = st.current
    if (!playing) {
      cancelAnimationFrame(s.raf)
      audio.current?.pause()
      rest()
      return
    }
    const au = audio.current
    let sound = !!(au && side.audio)
    let live = true
    const tick = () => {
      const t = sound && au ? au.currentTime : side.start + (performance.now() - s.t0) / 1000
      if (t >= side.end - 0.02) { onStop(); return }
      const k = locate(items, t)
      const it = items[k]
      const vs = els()
      if (k !== s.cur) {
        // the next shot was parked on the back picture: swap; else load it in front
        if (s.pre === k) s.front = 1 - s.front
        const f = vs[s.front], bk = vs[1 - s.front]
        if (f && it) {
          if (s.pre !== k) load(f, it, t)
          f.muted = sound
          f.playbackRate = it.speed ?? 1
          f.style.opacity = it.kind === 'shot' ? '1' : '0'
          dress(f, it, false)
          if (it.kind === 'shot') f.play().catch(() => {})
        }
        if (bk) {
          bk.pause()
          bk.style.opacity = '0'
          const nx = items[k + 1]
          s.pre = -1
          if (nx && nx.kind === 'shot' && nx.seq_start < side.end) { load(bk, nx, nx.seq_start); s.pre = k + 1 }
        }
        s.cur = k
      } else {
        const f = vs[s.front]
        if (f && it?.kind === 'shot' && Math.abs(f.currentTime - toSource(it, t)) > DRIFT) f.currentTime = toSource(it, t)
      }
      s.raf = requestAnimationFrame(tick)
    }
    // the picture starts with the sound (its mix may still be rendering), or alone if it can't play
    const begin = () => { if (live) { s.t0 = performance.now(); s.raf = requestAnimationFrame(tick) } }
    if (au && sound) {
      au.currentTime = side.start
      au.play().then(begin).catch(() => { sound = false; begin() })
    } else begin()
    // the video itself started playing: this version gives way, so two never sound at once
    const off = transportStore.subscribe(() => { if (transportStore.get().playing) onStop() })
    return () => { live = false; off(); cancelAnimationFrame(s.raf); au?.pause() }
  }, [playing, side]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <button type="button" onClick={() => (playing ? onStop() : onPlay())}
            aria-label={`${playing ? 'Stop' : 'Play'} version ${label}`}
            className="relative shrink-0 overflow-hidden rounded-xl bg-black"
            style={{ height: H, width: Math.round(H * ratio), maxWidth: '42vw' }}>
      {side.poster && !playing && <img src={side.poster} alt="" draggable={false} className="absolute inset-0 size-full object-contain" />}
      <video ref={a} muted playsInline preload="auto" className="absolute inset-0 size-full object-contain" />
      <video ref={b} muted playsInline preload="auto" aria-hidden className="absolute inset-0 size-full object-contain" style={{ opacity: 0 }} />
      {side.audio && <audio ref={audio} src={side.audio} preload="auto" />}
      <span className="absolute left-2 top-2 rounded-md bg-black/60 px-2 py-0.5 font-serif text-[15px] text-white">{label}</span>
      {!playing && <span className="absolute inset-0 grid place-items-center">
        <span className="rounded-full bg-black/60 px-4 py-2 font-serif text-[16px] text-white">▶ Play</span>
      </span>}
    </button>
  )
}
