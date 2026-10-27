import { useEffect, useRef, useState, type RefObject } from 'react'
import type { Segment } from '../types'
import { dur } from '../format'
import { hideStill, settleStill, swapSource } from '../hold'
import { OverlayCanvas, type OverlayEdit, type OverlayView } from './OverlayCanvas'
import { FxDefs } from './Effects'

// One <video> element. Two drivers share it: a preview (a span or a queue
// of spans from the shelf or a storyboard card, via `segment`) and the
// timeline transport, which drives the element directly through `videoRef`.
// With no segment, this component leaves the element alone.
//
// When the transport drives it, the picture sits in a stage with the
// export's shape (scaled to fit and padded, as the export does) and the
// words on screen are drawn over it -- so the preview is the export.
export function Player({ videoRef, backRef, veilRef, bars, segment, label, gap, onTime, onEnd, onPlayingChange, overlay, frame, overlayEdit, dark, controls }: {
  videoRef: RefObject<HTMLVideoElement | null>
  // the next shot, waiting (transport.ts), and the dip/flash veil -- the join as the export renders it
  backRef?: RefObject<HTMLVideoElement | null>
  veilRef?: RefObject<HTMLDivElement | null>
  bars?: number                    // cinematic bars, each as a share of the frame's height
  segment: Segment | null
  label: string
  gap: boolean
  onTime: (t: number) => void
  onEnd: () => void
  onPlayingChange: (playing: boolean) => void
  overlay?: OverlayView | null
  overlayEdit?: OverlayEdit
  frame?: { w: number; h: number } | null
  /** the edit screen: the picture on black, with `controls` under it instead of the label */
  dark?: boolean
  controls?: React.ReactNode
}) {
  const seg = useRef<Segment | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const [room, setRoom] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setRoom({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const el = videoRef.current
    seg.current = segment
    if (!el || !segment) return
    const src = `/api/video/${segment.clipId}`
    hideStill()
    const go = () => {
      if (seg.current !== segment) return // another preview took over while this one loaded
      el.currentTime = segment.start
      // A paused element after the seek is what showed black (sarah, 2026-10-14,
      // a left-out clip in Frames): if Safari won't start it with sound once the
      // click is long past, start it muted rather than leave nothing playing,
      // and keep the decoded frame up either way.
      if (segment.autoplay) {
        el.play().catch(() => {
          el.muted = true
          el.play().catch(() => settleStill(el))
        })
      } else settleStill(el)
    }
    // Seek once a frame has arrived, not just the metadata: Safari paints
    // black for a seek made before any frame data is in (transport.ts does the same).
    if (el.getAttribute('src') !== src) {
      el.addEventListener('loadeddata', go, { once: true })
      swapSource(el, src)
    } else if (el.readyState >= 2) {
      go()
    } else {
      el.addEventListener('loadeddata', go, { once: true })
    }
  }, [segment, videoRef])

  // The stage: the export's aspect, fitted into the room.
  const staged = !segment && !!frame && room.w > 0
  let stage = { left: 0, top: 0, w: room.w, h: room.h }
  if (staged) {
    const s = Math.min(room.w / frame!.w, room.h / frame!.h)
    const w = frame!.w * s
    const h = frame!.h * s
    stage = { left: (room.w - w) / 2, top: (room.h - h) / 2, w, h }
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${dark ? 'bg-[#121212]' : 'bg-raised'}`}>
      <div ref={box} className={`relative min-h-0 flex-1 ${dark ? 'm-4 mb-2' : ''}`}>
        <div className="absolute overflow-hidden bg-black" style={staged
          ? { left: stage.left, top: stage.top, width: stage.w, height: stage.h }
          : { inset: 0 }}>
          {/* the blur behind a whole picture where filling the frame would cut a face (transport.paint) */}
          <canvas data-backdrop className="pointer-events-none absolute inset-0 size-full" style={{ zIndex: 0, visibility: 'hidden' }} />
          <video
            ref={videoRef}
            className={`absolute inset-0 size-full object-contain ${gap ? 'invisible' : ''}`}
            playsInline preload="auto"
            onTimeUpdate={(e) => {
              const s = seg.current
              if (!s) return
              const t = e.currentTarget.currentTime
              onTime(Math.max(0, t - s.start))
              if (t >= s.end - 0.04) {
                e.currentTarget.pause()
                onEnd()
              }
            }}
            onPlay={() => onPlayingChange(true)}
            onPause={() => onPlayingChange(false)}
          />
          {backRef && <video ref={backRef} muted playsInline aria-hidden
                             className={`pointer-events-none absolute inset-0 size-full object-contain ${gap ? 'invisible' : ''}`}
                             style={{ opacity: 0 }} />}
          {/* each shot's effect: what lies over the picture (flashes, corners, scanlines, grain; transport.paint) */}
          {veilRef && <>
            <FxDefs id="vcfx" />
            <div data-fx-tint className={`pointer-events-none absolute inset-0 z-[3] ${segment ? 'invisible' : ''}`} />
            <div data-fx-grain className={`pointer-events-none absolute inset-0 z-[3] mix-blend-overlay ${segment ? 'invisible' : ''}`} style={{ opacity: 0 }} />
          </>}
          {/* The edit's dips and flashes; never over a clip previewed from the shelf
              (at a fade from black it covered the whole preview: sarah, 2026-10-14). */}
          {veilRef && <div ref={veilRef} className={`pointer-events-none absolute inset-0 z-[3] ${segment ? 'invisible' : ''}`} style={{ opacity: 0, background: 'black' }} />}
          {staged && !!bars && <>
            <div className="pointer-events-none absolute inset-x-0 top-0 z-[3] bg-black" style={{ height: `${bars * 100}%` }} />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] bg-black" style={{ height: `${bars * 100}%` }} />
          </>}
          {/* the last frame, held while the next clip loads (hold.ts) */}
          <canvas data-hold className={`pointer-events-none absolute inset-0 z-[4] size-full object-contain ${gap ? 'hidden' : ''}`} style={{ visibility: 'hidden' }} />
          {gap && <div className="absolute inset-0 grid place-items-center text-[11px] text-zinc-700">gap</div>}
          {staged && overlay && (overlay.items.length > 0 || !!overlay.graphics?.length) && <OverlayCanvas view={overlay} width={stage.w} height={stage.h} edit={overlayEdit} />}
        </div>
      </div>
      {controls ?? (
        <div className="flex h-7 shrink-0 items-center justify-between border-t border-line bg-panel px-3 text-[11px] text-muted">
          <span className="truncate">{label}</span>
          {segment && <span className="tabular-nums">{dur(segment.end - segment.start)}</span>}
        </div>
      )}
    </div>
  )
}
