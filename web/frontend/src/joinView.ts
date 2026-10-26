// What the picture does at each join, so the player shows what the export
// will have. The plan comes from the backend (export.plan_transitions, the
// same code that renders the file): per shot, frames of handle for a
// dissolve, and any dip to black or flash to white at its edges. Pure
// functions of the sequence time -- the transport applies them each frame.

import { mediaUrl, toMedia, type SeqItem } from './sequence.ts'

export type Trans = { key: string; head: number; tail: number; fade_in: [number, string] | null; fade_out: [number, string] | null
  /** on the outgoing shot: how the two pictures blend (transitions.py); null = a dissolve */
  blend?: string | null
  /** the blend is a swipe (kept for older callers; same as blend === 'swipe') */
  swipe?: boolean }
export type TransMap = Map<string, Trans>

export const byKey = (list: Trans[] | undefined | null): TransMap => new Map((list ?? []).map((t) => [t.key, t]))

/** A dip or flash veil over the picture at t: {colour, opacity}, or null.
 *  Export fades the shot's own frames linearly to the colour; a veil of the
 *  same colour at the same opacity is the same picture. */
export function veilAt(items: SeqItem[], k: number, tr: TransMap, t: number, fps: number): { color: string; alpha: number } | null {
  const it = items[k]
  const p = it && tr.get(it.key)
  if (!it || !p) return null
  if (p.fade_in) {
    const d = p.fade_in[0] / fps
    if (t < it.seq_start + d) return { color: p.fade_in[1], alpha: 1 - Math.max(0, t - it.seq_start) / d }
  }
  if (p.fade_out) {
    const d = p.fade_out[0] / fps
    if (t > it.seq_end - d) return { color: p.fade_out[1], alpha: Math.min(1, (t - (it.seq_end - d)) / d) }
  }
  return null
}

/** The dissolve at the cut after item k: its window in sequence time and
 *  where the incoming shot starts playing (its source time at window start).
 *  Export overlaps the two shots over [cut - head, cut + tail], mixing
 *  linearly; null when that cut is a plain cut. */
export function dissolveAfter(items: SeqItem[], k: number, tr: TransMap, fps: number):
  { from: number; cut: number; to: number; inFrom: number; blend: string; swipe: boolean } | null {
  const a = items[k], b = items[k + 1]
  if (!a || !b || a.kind !== 'shot' || b.kind !== 'shot') return null
  const tail = (tr.get(a.key)?.tail ?? 0) / fps, head = (tr.get(b.key)?.head ?? 0) / fps
  if (tail <= 0 && head <= 0) return null
  const cut = a.seq_end
  const blend = tr.get(a.key)?.blend ?? (tr.get(a.key)?.swipe ? 'swipe' : 'dissolve')
  return { from: cut - head, cut, to: cut + tail, inFrom: b.src_start - head, blend, swipe: blend === 'swipe' }
}

// The export's swipe (export.SWIPE_BLUR / SWIPE_SMEAR): xfade's slideleft,
// smeared sideways over the middle of the move.
export const SWIPE_BLUR = 0.03
export const SWIPE_SMEAR: [number, number] = [0.2, 0.8]

/** Where the two pictures sit at t inside a swipe window: the incoming one
 *  slides in from the right as the outgoing one leaves to the left (shares
 *  of the frame width), and whether the move is smeared. */
export function swipeAt(d: { from: number; to: number }, t: number): { outX: number; inX: number; smear: boolean } {
  const p = mixAt(d, t)
  return { outX: -p, inX: 1 - p, smear: p > SWIPE_SMEAR[0] && p < SWIPE_SMEAR[1] }
}

/** How much of the incoming shot shows at t inside a dissolve window (0..1). */
export function mixAt(d: { from: number; to: number }, t: number): number {
  return d.to > d.from ? Math.max(0, Math.min(1, (t - d.from) / (d.to - d.from))) : 1
}

/** Where to have the next shot waiting before its cut: its first source
 *  second, or earlier by its dissolve handle. */
export function preloadAt(items: SeqItem[], k: number, tr: TransMap, fps: number): { clip: string; url: string; t: number } | null {
  const b = items[k + 1]
  if (!b || b.kind !== 'shot' || !b.clip_id) return null
  const head = (tr.get(b.key)?.head ?? 0) / fps
  return { clip: b.clip_id, url: mediaUrl(b), t: Math.max(0, toMedia(b, b.seq_start) - head) }
}

/** How each picture looks at progress m (0..1) through a blend, as the
 *  export's xfade draws it (export._xfade): the outgoing shot, the incoming
 *  one on top, and a coloured glow over both for a light leak. CSS's own
 *  translate / scale / filter, so the shot's turn and mirror (transport.dress,
 *  on `transform`) still apply underneath. */
export type Pic = { opacity: number; translate: string; scale: string; filter: string }
export function blendLook(kind: string, m: number): { out: Pic; in: Pic; glow: { background: string; alpha: number } | null } {
  const plain: Pic = { opacity: 1, translate: '', scale: '', filter: '' }
  const ease = m * m * (3 - 2 * m)
  switch (kind) {
    case 'zoom':      // push into the outgoing shot, the next one fades up out of it
      return { out: { ...plain, scale: String(1 + 0.9 * ease), filter: `blur(${(6 * ease).toFixed(1)}px)` },
               in: { ...plain, opacity: Math.max(0, Math.min(1, (m - 0.35) / 0.65)) }, glow: null }
    case 'slide_up':  // the next shot pushes this one up, like scrolling
      return { out: { ...plain, translate: `0 ${(-100 * m).toFixed(2)}%` },
               in: { ...plain, translate: `0 ${(100 * (1 - m)).toFixed(2)}%` }, glow: null }
    case 'swipe': {   // a whip: out to the left, in from the right, smeared mid-move (swipeAt)
      const sw = swipeAt({ from: 0, to: 1 }, m)
      const f = sw.smear ? `blur(${(SWIPE_BLUR * 100).toFixed(1)}px)` : ''
      return { out: { ...plain, translate: `${(100 * sw.outX).toFixed(2)}% 0`, filter: f },
               in: { ...plain, translate: `${(100 * sw.inX).toFixed(2)}% 0`, filter: f }, glow: null }
    }
    case 'blur':      // goes soft, comes back sharp on the next
      return { out: { ...plain, filter: `blur(${(14 * m).toFixed(1)}px)` },
               in: { ...plain, opacity: m, filter: `blur(${(14 * (1 - m)).toFixed(1)}px)` }, glow: null }
    case 'light_leak': {   // a warm glow sweeps across the cut (transitions.LIGHT_LEAK)
      const x = (140 * m - 20).toFixed(1)
      return { out: plain, in: { ...plain, opacity: m },
               glow: { background: `radial-gradient(circle at ${x}% 40%, rgba(255,196,110,.95), rgba(255,120,60,.6) 35%, rgba(255,120,60,0) 70%)`,
                       alpha: Math.sin(Math.PI * m) } }
    }
    default:          // dissolve
      return { out: plain, in: { ...plain, opacity: m }, glow: null }
  }
}
