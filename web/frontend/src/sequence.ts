// The edit as a sequence of spans, and the arithmetic of time on it.

export type SeqItem = {
  key: string
  kind: 'shot' | 'gap'
  shot_id: string | null
  clip_id: string | null
  src_start: number
  src_end: number
  src_min?: number   // how far the ends can be dragged: the whole shot as filmed
  src_max?: number
  seq_start: number
  seq_end: number
  beat_id: string
  beat_title: string
  n: number | null
  // the shot menu's fixes (backend board.set_shot), only where set
  speed?: number     // 2 = twice as fast: half as long in the edit
  gain?: number
  mute?: boolean
  rotate?: number    // quarter turns, clockwise
  punch?: number     // the camera's push over the shot: + in, - out (board set_shot)
  fill?: boolean     // cover the frame, edges cropped
  aim?: [number, number] | null   // a filled shot's crop centre in its picture (Make, aim.py); none = the middle
  backdrop?: 'blur' | null        // the whole picture over a blur of itself (Make, where filling would cut a face)
  mirror?: boolean   // flipped left to right
  fade_in?: number   // its own sound fading in / out, seconds
  fade_out?: number
  effect?: string | null   // Shake, VHS... (backend effects.py), drawn by effectView
  effect_amount?: number   // its Strength, 1 = 100%
  reverse?: boolean  // plays backwards (backend reverse.py makes the file the player shows)
  freeze?: boolean   // a held frame: shows src_start for the whole span (board freeze_frame)
}

/** Index of the item under t (binary search). The very end belongs to the
 *  last item, so the playhead parked at the end still has a context. */
export function locate(items: SeqItem[], t: number): number {
  if (!items.length) return -1
  let lo = 0
  let hi = items.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (items[mid].seq_start <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Source time inside the item under t: what the edit's tools (split, trim,
 *  remove) send. Backwards, the span plays from its end. A held frame keeps
 *  plain arithmetic over its span (the board reads it as a length). */
export function toSource(item: SeqItem, t: number): number {
  const d = (t - item.seq_start) * (item.speed ?? 1)
  return item.reverse ? item.src_end - d : item.src_start + d
}

/** The file the player shows for an item: the clip, or its span made backwards. */
export function mediaUrl(item: SeqItem): string {
  return item.reverse
    ? `/api/reversed/${item.clip_id}?a=${item.src_start}&b=${item.src_end}`
    : `/api/video/${item.clip_id}`
}

/** Time in that file at edit time t (a held frame: always its one frame). */
export function toMedia(item: SeqItem, t: number): number {
  if (item.freeze) return item.src_start
  const d = (t - item.seq_start) * (item.speed ?? 1)
  return item.reverse ? d : item.src_start + d
}

/** Edit time when that file is at `ct`. */
export function fromMedia(item: SeqItem, ct: number): number {
  return item.seq_start + (item.reverse ? ct : ct - item.src_start) / (item.speed ?? 1)
}

/** Where the item's part of that file ends. */
export function mediaEnd(item: SeqItem): number {
  return item.reverse ? item.src_end - item.src_start : item.src_end
}

/** "21.3", "0:21.3", "1:02:03.5", or SMPTE "00:00:21:09" -> seconds.
 *  Four colon-separated fields are hh:mm:ss:ff at the sequence frame rate. */
export function parseTimecode(input: string, fps: number): number | null {
  const s = input.trim()
  if (!s) return null
  const parts = s.split(':')
  if (parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null
  const n = parts.map(Number)
  if (parts.length === 4) {
    if (parts.slice(0, 4).some((p) => p.includes('.')) || n[3] >= fps || n[2] >= 60 || n[1] >= 60) return null
    return n[0] * 3600 + n[1] * 60 + n[2] + n[3] / fps
  }
  if (parts.length > 3) return null
  if (parts.slice(0, -1).some((p) => p.includes('.'))) return null
  if (parts.length >= 2 && n[n.length - 1] >= 60) return null
  if (parts.length === 3 && n[1] >= 60) return null
  return n.reduce((acc, v) => acc * 60 + v, 0)
}

/** 0:21.30 -- minutes, seconds, hundredths. */
export function clock(t: number): string {
  const neg = t < 0
  t = Math.abs(t)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const s = (t % 60).toFixed(2).padStart(5, '0')
  return (neg ? '-' : '') + (h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`)
}

/** 00:00:21:09 at the sequence frame rate. */
export function smpte(t: number, fps: number): string {
  const f = Math.round(Math.max(0, t) * fps)
  const ff = f % fps
  const secs = Math.floor(f / fps)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${p(Math.floor(secs / 3600))}:${p(Math.floor((secs % 3600) / 60))}:${p(secs % 60)}:${p(ff)}`
}

export type Grid = { bpm: number; phase: number } | null

/** Which beat of the music is at t, if a track with a tempo is under the edit. */
export function beatAt(grid: Grid, t: number): { beat: number; bar: number } | null {
  if (!grid) return null
  const period = 60 / grid.bpm
  const k = Math.floor((t - grid.phase) / period + 1e-6)
  if (k < 0) return null
  return { beat: (k % 4) + 1, bar: Math.floor(k / 4) + 1 }
}

/** "Shot 12 · 2.1s in · 0:21.30 · beat 3 of 4" */
export function readout(items: SeqItem[], grid: Grid, t: number): string {
  const k = locate(items, t)
  if (k < 0) return clock(t)
  const it = items[k]
  const parts = [
    it.kind === 'gap' ? 'Gap' : `Shot ${it.n}`,
    `${(t - it.seq_start).toFixed(1)}s in`,
    clock(t),
  ]
  const b = beatAt(grid, t)
  if (b) parts.push(`beat ${b.beat} of 4`)
  return parts.join(' · ')
}
