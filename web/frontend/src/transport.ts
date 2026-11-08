// Playback of the edit: one <video>, driven span by span over the sequence.
//
// The playhead position lives in a tiny store, not React state, so moving
// it 60 times a second re-renders only what shows it (timeline, readout)
// instead of the whole app.
import { useSyncExternalStore } from 'react'
import { fromMedia, locate, mediaEnd, mediaUrl, toMedia, toSource, type SeqItem } from './sequence'
import { aimPosition, drawBackdrop } from './aimView'
import type { Target } from './snap'
import { hideStill, settleStill, swapSource } from './hold'
import { blendLook, dissolveAfter, mixAt, preloadAt, veilAt, type Pic, type TransMap } from './joinView'
import { effectAt, noise, tuneSvg, NO_FX, type FxLook } from './effectView'

export function createStore<T>(initial: T) {
  let v = initial
  const ls = new Set<() => void>()
  return {
    get: () => v,
    set: (nv: T) => { if (nv !== v) { v = nv; ls.forEach((l) => l()) } },
    subscribe: (l: () => void) => { ls.add(l); return () => { ls.delete(l) } },
  }
}
type Store<T> = ReturnType<typeof createStore<T>>
export function useStore<T>(s: Store<T>): T {
  return useSyncExternalStore(s.subscribe, s.get)
}

export const phStore = createStore(0)
export type TransportState = { playing: boolean; rate: number; gap: boolean }
export const transportStore = createStore<TransportState>({ playing: false, rate: 0, gap: false })
// What the playhead last snapped to (or is closing in on) -- shown by name.
export type SnapInfo = { target: Target; snapped: boolean } | null
export const snapStore = createStore<SnapInfo>(null)

const EPS = 0.5 / 30
// Same as the export's (backend audiomix.MUSIC_GAIN): the preview must not
// sound louder than the file. Only used when the mixed track can't play.
export const MUSIC_GAIN = 0.35

export class Transport {
  video: HTMLVideoElement | null = null
  audio: HTMLAudioElement | null = null   // music under the edit, if any (fallback)
  // The edit's whole sound, mixed by the backend exactly as export will write
  // it: joins carried or cut, micro-fades, the music bed. While it plays the
  // picture is muted, so every cut stops cutting the sound.
  mix: HTMLAudioElement | null = null
  mixBroken = false
  // A second <video> for the next shot, loaded and parked on its first frame
  // before the cut: the cut is a swap, not a seek, and a dissolve plays both.
  // `primary` is the element the rest of the app (previews) knows about;
  // whenever playback stops it is put back in front.
  primary: HTMLVideoElement | null = null
  back: HTMLVideoElement | null = null
  veil: HTMLDivElement | null = null
  trans: TransMap = new Map()
  fps = 30
  private pre: { k: number; url: string; t: number; ready: boolean } | null = null
  private leaving: { el: HTMLVideoElement; from: number; to: number; blend: string } | null = null
  items: SeqItem[] = []
  total = 0
  private raf = 0
  private last = 0
  private cur = -1
  private switching = false
  private seekQueued: number | null = null
  private seeking = false
  private lastDrift = 0

  /** The player's two pictures and its veil (Player.tsx). */
  attach(primary: HTMLVideoElement | null, back: HTMLVideoElement | null, veil: HTMLDivElement | null) {
    // a new player (Watch to the editor): the old pictures are gone, stop on them first
    if (primary && this.primary && primary !== this.primary && transportStore.get().playing) this.stop()
    if (!transportStore.get().playing) this.video = primary
    this.primary = primary
    this.back = back
    this.veil = veil
    if (back) back.muted = true
    this.paint(phStore.get())
  }

  setTransitions(trans: TransMap, fps: number) {
    this.trans = trans
    this.fps = fps
    this.pre = null
  }

  setItems(items: SeqItem[], total: number) {
    const changed = items !== this.items
    const sameLength = Math.abs(total - this.total) < 1e-6
    this.items = items
    this.total = total
    if (changed && transportStore.get().playing) {
      // A cut changes the pieces, not the timing: keep playing through it.
      if (sameLength && transportStore.get().rate > 0) this.cur = locate(items, phStore.get())
      else this.stop()
    }
    if (phStore.get() > total) phStore.set(total)
    if (!transportStore.get().playing && !this.lent) this.showFrame(phStore.get())
  }

  // While the player shows a single clip from the shelf (a preview), the edit
  // must not take the picture back: a session refresh used to put the edit's
  // frame (or, mid-load, nothing) where the clip should be playing.
  private lent = false
  /** Hand the primary element to a preview until the edit next seeks or plays. */
  lend() {
    this.stop()
    dress(this.primary, null)   // a clip from the shelf plays as filmed
    this.lent = true
    this.seekQueued = null
  }

  private state(p: Partial<TransportState>) {
    transportStore.set({ ...transportStore.get(), ...p })
  }

  // the index frame nearest a moment of a clip, put up while a jump loads
  private sampleAt: (clipId: string, srcT: number) => string | null = () => null
  setSamples(fn: (clipId: string, srcT: number) => string | null) { this.sampleAt = fn }

  /** Load the item's file (the clip, or its span made backwards). */
  private async ensureClip(it: SeqItem, srcT?: number) {
    const v = this.video
    if (!v) return
    const url = mediaUrl(it), clipId = it.clip_id!
    if (v.getAttribute('src') === url && v.readyState >= 2) return
    // Wait for a decodable frame, not just the metadata: Safari paints black
    // for a seek made before any frame data has arrived (the first jump on
    // the timeline after loading). Never wait forever on a stuck load.
    await new Promise<void>((res) => {
      const done = () => { clearTimeout(timer); v.removeEventListener('loadeddata', done); res() }
      const timer = setTimeout(done, 4000)
      v.addEventListener('loadeddata', done)
      if (v.getAttribute('src') !== url) swapSource(v, url, srcT == null ? null : this.sampleAt(clipId, srcT))
      else if (v.readyState >= 2) done()
    })
  }

  /** Move the playhead. Paused: shows that frame. */
  seek(t: number) {
    this.lent = false
    t = Math.max(0, Math.min(t, this.total))
    phStore.set(t)
    if (!transportStore.get().playing) this.showFrame(t)
    else if (transportStore.get().rate > 0) this.play(transportStore.get().rate)
  }

  // Coalesce paused seeks: while one is in flight, keep only the latest.
  private showFrame(t: number) {
    hideStill()
    this.seekQueued = t
    if (this.seeking) return
    this.seeking = true
    ;(async () => {
      while (this.seekQueued != null) {
        const at = this.seekQueued
        this.seekQueued = null
        const k = locate(this.items, at)
        const it = this.items[k]
        if (!it || this.lent) break
        if (it.kind === 'gap') { this.state({ gap: true }); continue }
        this.state({ gap: false })
        await this.ensureClip(it, toSource(it, at))
        if (this.lent) break
        if (this.video) this.video.currentTime = Math.min(toMedia(it, at), mediaEnd(it) - EPS)
        dress(this.video, it)
        this.paint(at)
      }
      this.seeking = false
      if (this.video && !transportStore.get().playing) settleStill(this.video)
    })()
  }

  play(rate = 1) {
    this.lent = false
    if (!this.items.length || !this.video) return
    hideStill()
    cancelAnimationFrame(this.raf)
    this.state({ playing: true, rate })
    if (rate > 0) this.forward(rate)
    else this.reverse(rate)
  }

  stop() {
    cancelAnimationFrame(this.raf)
    this.video?.pause()
    this.back?.pause()
    this.audio?.pause()
    this.mix?.pause()
    this.front()
    if (this.video) this.video.muted = false   // shelf previews play their own sound
    this.state({ playing: false, rate: 0 })
    this.paint(phStore.get())
  }

  /** Put the primary element back in front (previews and scrubbing use it). */
  private front() {
    this.leaving = null
    this.pre = null
    if (this.primary && this.video !== this.primary) {
      this.back = this.video
      this.video = this.primary
      if (this.back) this.back.muted = true
      // the primary takes over the picture at the playhead (held while it loads)
      this.showFrame(phStore.get())
      return
    }
    if (this.back) this.back.muted = true
  }

  /** Which picture is on top, how see-through, and the dip veil, at t. */
  private paint(t: number) {
    const v = this.video, b = this.back
    let top = v, under: HTMLVideoElement | null = null
    let look: ReturnType<typeof blendLook> | null = null
    if (this.leaving && v) {
      top = v; under = this.leaving.el; look = blendLook(this.leaving.blend, mixAt(this.leaving, t))
    } else if (b && v && !b.paused) {
      const d = dissolveAfter(this.items, this.cur, this.trans, this.fps)
      if (d) { top = b; under = v; look = blendLook(d.blend, mixAt(d, t)) }
    }
    // each picture's own effect (effectView), at its own moment of its shot
    const k0 = locate(this.items, t)
    const shown = (el: HTMLVideoElement): SeqItem | undefined =>
      this.leaving?.el === el ? this.items[k0 - 1] : el === b && top === b ? this.items[this.cur + 1] : this.items[k0]
    const fxOf = (el: HTMLVideoElement): FxLook => {
      const it = shown(el)
      if (!it || it.kind !== 'shot' || !it.effect || this.lent) return NO_FX
      const fx = effectAt(it.effect, it.effect_amount, t - it.seq_start, it.seq_end - it.seq_start, el.clientWidth, el.clientHeight)
      tuneSvg(fx)
      return fx
    }
    let topFx = NO_FX
    const put = (el: HTMLVideoElement, z: string, p: Pic | null, opacity: number, fx: FxLook) => {
      el.style.zIndex = z
      el.style.opacity = String(p ? p.opacity : opacity)
      el.style.translate = p?.translate ?? ''
      el.style.scale = p?.scale ?? ''
      el.style.filter = [p?.filter ?? '', fx.filter].join(' ').trim()
      el.style.transform = [fx.transform, el.dataset.dress ?? ''].join(' ').trim()
    }
    for (const el of [v, b]) {
      if (!el) continue
      if (el === top) { topFx = fxOf(el); put(el, '2', look?.in ?? null, 1, topFx) }
      else if (el === under) put(el, '1', look?.out ?? null, 1, fxOf(el))
      else put(el, '0', null, 0, NO_FX)
    }
    const stage = this.veil?.parentElement
    // a whole picture over a blur of itself (board backdrop): the blur, drawn from the picture on top
    const backdrop = (stage ?? top?.parentElement)?.querySelector<HTMLCanvasElement>('canvas[data-backdrop]')
    if (backdrop) {
      const it = top ? shown(top) : undefined
      const on = !!top && !this.lent && it?.kind === 'shot' && it.backdrop === 'blur' && drawBackdrop(backdrop, top)
      backdrop.style.visibility = on ? 'visible' : 'hidden'
    }
    const tint = stage?.querySelector<HTMLDivElement>('[data-fx-tint]')
    const grain = stage?.querySelector<HTMLDivElement>('[data-fx-grain]')
    if (tint) tint.style.background = topFx.tint
    if (grain) {
      grain.style.opacity = String(topFx.grain)
      if (topFx.grain) {
        grain.style.backgroundImage = `url(${noise()})`
        grain.style.backgroundPosition = `${Math.floor(Math.random() * 128)}px ${Math.floor(Math.random() * 128)}px`
      }
    }
    if (this.veil) {
      const k = locate(this.items, t)
      const w = k < 0 ? null : veilAt(this.items, k, this.trans, t, this.fps)
      // a light leak's glow uses the same veil (a blend has no dip or flash at its cut)
      const g = look?.glow
      this.veil.style.opacity = w ? String(w.alpha) : g ? String(g.alpha) : '0'
      if (w) this.veil.style.background = w.color
      else if (g) this.veil.style.background = g.background
    }
  }

  /** Have the shot after item k waiting in the back element. */
  private preload(k: number) {
    const b = this.back
    if (!b || this.leaving) return
    const target = preloadAt(this.items, k, this.trans, this.fps)
    const it = this.items[k], nx = this.items[k + 1]
    if (!target || (it && nx && seamless(it, nx))) {
      return   // nothing next, or the other half of a cut: the front keeps playing
    }
    if (this.pre && this.pre.k === k + 1 && this.pre.url === target.url && Math.abs(this.pre.t - target.t) < 1e-3) return
    const pre = { k: k + 1, url: target.url, t: target.t, ready: false }
    this.pre = pre
    b.pause()
    const url = target.url
    const park = () => {
      if (this.pre !== pre) return
      b.addEventListener('seeked', () => { if (this.pre === pre) pre.ready = true }, { once: true })
      dress(b, this.items[k + 1], false)
      b.currentTime = target.t
    }
    if (b.getAttribute('src') !== url) {
      b.addEventListener('loadedmetadata', park, { once: true })
      b.setAttribute('src', url)
      b.load()
    } else park()
  }

  private mixUsable() {
    return !!this.mix && !this.mixBroken && !this.mix.error && !!this.mix.getAttribute('src') && this.mix.readyState >= 2
  }

  /** The bed that follows the playhead: the mix if it plays, else the plain music. */
  private bed(rate: number): HTMLAudioElement | null {
    const useMix = rate === 1 && this.mixUsable()
    if (this.video) this.video.muted = useMix
    if (this.back) this.back.muted = true   // the waiting (or leaving) picture never speaks
    if (useMix) { this.audio?.pause(); return this.mix }
    this.mix?.pause()
    if (this.audio) this.audio.volume = MUSIC_GAIN
    return this.audio
  }

  private async enter(k: number, t: number, rate: number) {
    const it = this.items[k]
    const v = this.video!
    if (it.kind === 'gap') { v.pause(); this.state({ gap: true }); return }
    this.state({ gap: false })
    await this.ensureClip(it)
    v.currentTime = toMedia(it, t)
    dress(v, it)
    if (it.freeze) { v.pause(); return }   // a held frame: the clock moves, the picture doesn't
    v.playbackRate = rate * (it.speed ?? 1)
    await v.play().catch(() => {})
  }

  private syncMusic(t: number, rate: number, force = false) {
    const a = this.bed(rate)
    if (!a) return
    if (rate !== 1) { a.pause(); return }
    const now = performance.now()
    const drift = a.currentTime - t
    if (a === this.mix) {
      // The mix is the whole sound: a seek is heard as a skip, so small drift
      // (the picture pausing to change file at a cut) is absorbed by playing
      // the sound a touch slower or faster; only a big one is re-seeked.
      if (force || Math.abs(drift) > 0.3) {
        a.currentTime = t
        a.playbackRate = 1
        this.lastDrift = now
      } else {
        a.playbackRate = Math.abs(drift) < 0.02 ? 1 : Math.max(0.94, Math.min(1.06, 1 - drift * 0.6))
      }
    } else if (force || (now - this.lastDrift > 500 && Math.abs(drift) > 0.12)) {
      a.currentTime = t
      this.lastDrift = now
    }
    if (a.paused) a.play().catch(() => { if (a === this.mix) this.mixBroken = true })
  }

  private async forward(rate: number) {
    let t = phStore.get()
    if (t >= this.total - EPS) { t = 0; phStore.set(0) }
    this.back?.pause()
    this.front()
    this.cur = locate(this.items, t)
    this.switching = true
    this.bed(rate)   // mute the picture before it starts if the mix will carry the sound
    await this.enter(this.cur, t, rate)
    this.switching = false
    this.syncMusic(t, rate, true)
    this.last = performance.now()
    const tick = (now: number) => {
      if (!transportStore.get().playing) return
      const dt = (now - this.last) / 1000
      this.last = now
      if (!this.switching) {
        const it = this.items[this.cur]
        let pos: number
        let done: boolean
        if (it.kind === 'gap' || it.freeze) {
          pos = phStore.get() + dt * rate
          done = pos >= it.seq_end
        } else {
          const ct = this.video!.currentTime
          pos = fromMedia(it, ct)
          done = ct >= mediaEnd(it) - EPS || this.video!.ended
        }
        this.preload(this.cur)
        // a dissolve starts the next shot early, under the end of this one
        const d = rate === 1 ? dissolveAfter(this.items, this.cur, this.trans, this.fps) : null
        if (d && pos >= d.from && this.pre?.k === this.cur + 1 && this.pre.ready && this.back?.paused) {
          // start where the playhead already is inside the window, not at its edge
          this.back.currentTime = d.inFrom + Math.max(0, pos - d.from)
          this.back.playbackRate = rate * (this.items[this.cur + 1]?.speed ?? 1)
          this.back.play().catch(() => {})
        }
        // the outgoing shot of a dissolve plays out its tail under the new one
        if (this.leaving && phStore.get() >= this.leaving.to) { this.leaving.el.pause(); this.leaving = null }
        if (done) {
          const next = this.cur + 1
          if (next >= this.items.length) { phStore.set(this.total); this.stop(); return }
          const nx = this.items[next]
          this.cur = next
          phStore.set(nx.seq_start)
          // the other half of a cut, straight after: keep playing, no seek
          const joined = seamless(it, nx)
          const pre = this.pre
          if (nx.kind === 'shot' && !joined && pre && pre.k === next && pre.ready && this.back) {
            // the next shot is already waiting: swap pictures, no seek, no flash
            const out = this.video!
            this.video = this.back
            this.back = out
            this.pre = null
            this.state({ gap: false })
            this.video.playbackRate = rate * (nx.speed ?? 1)
            if (nx.freeze) this.video.pause()
            else if (this.video.paused) {
              this.video.play().catch(() => {})
            }
            if (d && d.to > d.cut && it.kind === 'shot') this.leaving = { el: out, from: d.from, to: d.to, blend: d.blend }
            else out.pause()
          } else if (!joined) {
            this.switching = true
            this.enter(next, nx.seq_start, rate).then(() => { this.switching = false; this.last = performance.now() })
          }
        } else {
          phStore.set(Math.min(pos, it.seq_end))
        }
        this.paint(phStore.get())
        this.syncMusic(phStore.get(), rate)
      }
      this.raf = requestAnimationFrame(tick)
    }
    this.raf = requestAnimationFrame(tick)
  }

  // Browsers won't play video backwards; step the playhead and show frames.
  private reverse(rate: number) {
    this.video?.pause()
    this.audio?.pause()
    this.mix?.pause()
    this.last = performance.now()
    let lastShown = 0
    const tick = (now: number) => {
      if (!transportStore.get().playing) return
      const dt = (now - this.last) / 1000
      this.last = now
      const t = Math.max(0, phStore.get() + dt * rate)
      phStore.set(t)
      if (now - lastShown > 70) { this.showFrame(t); lastShown = now }
      if (t <= 0) { this.stop(); return }
      this.raf = requestAnimationFrame(tick)
    }
    this.raf = requestAnimationFrame(tick)
  }
}

export const transport = new Transport()

/** The other half of a cut, straight after: the same file runs on, no seek. */
function seamless(it: SeqItem, nx: SeqItem): boolean {
  return it.kind === 'shot' && nx.kind === 'shot' && nx.clip_id === it.clip_id
    && !it.reverse && !nx.reverse && !it.freeze && !nx.freeze
    && Math.abs(nx.src_start - it.src_end) < 0.02 && (nx.speed ?? 1) === (it.speed ?? 1)
    && (nx.rotate ?? 0) === (it.rotate ?? 0) && !!nx.fill === !!it.fill
    && JSON.stringify(nx.aim ?? null) === JSON.stringify(it.aim ?? null)
}


/** The shot menu's turn and fill on the picture, as export draws them
 *  (export._fit): the whole turned picture inside the frame, or covering it. */
export function dress(el: HTMLVideoElement | null, it: SeqItem | null | undefined, hold = true) {
  if (!el) return
  const r = it?.kind === 'shot' ? (it.rotate ?? 0) : 0
  const fill = it?.kind === 'shot' && !!it.fill
  const flip = it?.kind === 'shot' && it.mirror ? ' scaleX(-1)' : ''   // export mirrors before turning
  let transform = flip.trim(), fit = fill ? 'cover' : ''
  // a filled shot Make aimed at its people (board aim): the same crop the export cuts
  let position = fill && !r && it?.kind === 'shot'
    ? aimPosition(it.aim, el.clientWidth, el.clientHeight, el.videoWidth, el.videoHeight) : ''
  if (r) {
    fit = 'contain'
    const W = el.clientWidth || 1, H = el.clientHeight || 1
    const vw = el.videoWidth || W, vh = el.videoHeight || H
    const c = Math.min(W / vw, H / vh)        // the picture as shown, unturned
    const [w, h] = r % 180 ? [vh * c, vw * c] : [vw * c, vh * c]   // ...and turned
    const k = fill ? Math.max(W / w, H / h) : Math.min(W / w, H / h)
    transform = `rotate(${r}deg) scale(${k})${flip}`
  }
  // the push over the shot (board punch; export's zoompan): a slow scale, + in, - out
  const push = it?.kind === 'shot' ? (it.punch ?? 0) : 0
  const dur = it ? Math.max(0.2, it.seq_end - it.seq_start) : 0
  // the held frame laid over the picture (hold.ts) is the same picture: dress it alike
  const still = hold ? el.parentElement?.querySelector<HTMLCanvasElement>('canvas[data-hold]') : null
  for (const x of still ? [el, still] : [el]) {
    x.dataset.dress = transform   // paint() puts the shot's effect in front of it
    x.style.transform = transform
    x.style.objectFit = fit
    x.style.objectPosition = position
    if (push) {
      x.style.setProperty('--push-from', String(push > 0 ? 1 : 1 - push))
      x.style.setProperty('--push-to', String(push > 0 ? 1 + push : 1))
      x.style.animation = 'none'
      void x.offsetWidth   // restart the animation at each cut
      x.style.animation = `vc-push ${dur.toFixed(3)}s linear forwards`
    } else {
      x.style.animation = ''
      x.style.removeProperty('scale')
    }
  }
}

