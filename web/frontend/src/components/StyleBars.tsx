import { useEffect, useRef } from 'react'
import { blendLook } from '../joinView'
import { drawOverlays } from '../overlayDraw'
import type { CaptionEnter, CaptionTemplate, JoinInfo, Overlay, OverlayStyle } from '../types'
import { ENTER_NAMES, TEMPLATE_NAMES, TRANSITION_NAMES, useLoop } from '../styleNames'
import { cx } from '../ui'
import { Chip, Slider, type CaptionStylePatch } from './Inspector'

// The captions' Style and Animation, and the Transition at a cut, as tiles
// in the inspector's Captions and Effects tabs. Every choice is a tile that
// moves the way the result will, drawn by the same code as the preview and
// the export (overlayDraw.drawOverlays, joinView.blendLook), and one tap is
// one undoable turn. Nothing here is on by default: a video keeps its look's
// own captions and cuts until something is picked (sarah, 2026-10-14).

const TILE_W = 112, TILE_H = 76

export function Tile({ on, label, onClick, children }: { on: boolean; label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="flex shrink-0 flex-col items-center gap-1 font-serif text-[15px] text-zinc-100">
      <span className={cx('relative block overflow-hidden rounded-lg border-[3px] bg-black',
        on ? 'border-accent' : 'border-transparent hover:border-zinc-500')} style={{ width: TILE_W, height: TILE_H }}>
        {children}
      </span>
      {label}
    </button>
  )
}

/** A caption drawn on a tile exactly as drawOverlays will draw it in the video. */
export function CaptionSample({ style, text, t, scale = 3 }: { style: OverlayStyle; text: string; t: number; scale?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    const ctx = c?.getContext('2d')
    if (!c || !ctx) return
    const o: Overlay = { id: 'tile', kind: 'caption', text, sub: '', pos: 'bottom', size: 'L', anim: 'fade', dur: 3,
      anchor: { to: 'edit' }, at: 0, start: 0, end: 3, shown_end: 3, place: { x: 0.5, y: 0.5, scale } }
    drawOverlays(ctx, c.width, c.height, [o], style, [], t)
  }, [style, text, t, scale])
  return <canvas ref={ref} width={TILE_W * 2} height={TILE_H * 2} className="absolute inset-0 size-full" />
}

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] justify-items-center gap-x-2 gap-y-3'

type CaptionPick = (patch: CaptionStylePatch, label: string) => void
// a word art tile shows the art as it comes, and picking one starts it fresh
const PLAIN = { outline: null, shadow: null, backdrop: null, thick: null }

/** One style for every caption in the video. */
export function CaptionStyles({ style, thumb, onPick }: { style: OverlayStyle; thumb: string | null; onPick: CaptionPick }) {
  const bg = thumb ? { backgroundImage: `url(${thumb})`, backgroundSize: 'cover', backgroundPosition: 'center' } : undefined
  const held = 2.0   // the caption fully in
  return (
    <div className={GRID}>
      <Tile on={!style.template} label="Soft" onClick={() => style.template && onPick({ template: null, ...PLAIN }, 'Every caption is now Soft')}>
        <span className="absolute inset-0" style={bg} />
        <CaptionSample style={{ ...style, ...PLAIN, template: null, enter: null }} text="Aa" t={held} />
      </Tile>
      {(Object.keys(TEMPLATE_NAMES) as CaptionTemplate[]).map((id) => (
        <Tile key={id} on={style.template === id} label={TEMPLATE_NAMES[id]}
              onClick={() => style.template !== id && onPick({ template: id, ...PLAIN }, `Every caption is now ${TEMPLATE_NAMES[id]}`)}>
          <span className="absolute inset-0" style={bg} />
          <CaptionSample style={{ ...style, ...PLAIN, template: id, enter: null }} text="Aa" t={held} />
        </Tile>
      ))}
    </div>
  )
}

/** How every caption comes in, each tile playing it round and round. */
export function CaptionAnimations({ style, thumb, sample, onPick }: { style: OverlayStyle; thumb: string | null; sample: string; onPick: CaptionPick }) {
  const m = useLoop(2.2)
  const bg = thumb ? { backgroundImage: `url(${thumb})`, backgroundSize: 'cover', backgroundPosition: 'center' } : undefined
  return (
    <div className={GRID}>
      <Tile on={!style.enter} label="The look's own" onClick={() => style.enter && onPick({ enter: null }, 'Captions come in the look\'s own way')}>
        <span className="absolute inset-0" style={bg} />
        <CaptionSample style={{ ...style, enter: null }} text={sample} t={m * 2.2} scale={2} />
      </Tile>
      {(Object.keys(ENTER_NAMES) as CaptionEnter[]).map((id) => (
        <Tile key={id} on={style.enter === id} label={ENTER_NAMES[id]}
              onClick={() => style.enter !== id && onPick({ enter: id }, `Captions now come in: ${ENTER_NAMES[id]}`)}>
          <span className="absolute inset-0" style={bg} />
          <CaptionSample style={{ ...style, enter: id }} text={sample} t={m * 2.2} scale={2} />
        </Tile>
      ))}
    </div>
  )
}

/** Two pictures joined the way `kind` joins them, playing round and round. */
export function JoinSample({ kind, from, to, m }: { kind: string; from: string | null; to: string | null; m: number }) {
  // hold the outgoing shot, run the join through the middle half, hold the next
  const k = Math.max(0, Math.min(1, (m - 0.25) / 0.5))
  const pic = (src: string | null) => src ? { backgroundImage: `url(${src})`, backgroundSize: 'cover', backgroundPosition: 'center' } : { background: '#444' }
  if (kind === 'cut' || kind === 'dip_black' || kind === 'flash') {
    const veil = kind === 'cut' ? 0 : 1 - Math.abs(k - 0.5) * 2
    return <>
      <span className="absolute inset-0" style={pic(k < 0.5 ? from : to)} />
      <span className="absolute inset-0" style={{ background: kind === 'flash' ? 'white' : 'black', opacity: veil }} />
    </>
  }
  const look = blendLook(kind, k)
  const css = (p: typeof look.out) => ({ opacity: p.opacity, translate: p.translate, scale: p.scale,
    filter: p.filter.replace(/([\d.]+)px/, (_, n) => `${(Number(n) / 3).toFixed(1)}px`) })
  return <>
    <span className="absolute inset-0" style={{ ...pic(from), ...css(look.out) }} />
    <span className="absolute inset-0" style={{ ...pic(to), ...css(look.in) }} />
    {look.glow && <span className="absolute inset-0" style={{ background: look.glow.background, opacity: look.glow.alpha }} />}
  </>
}

type JoinPick = (op: { kind: string; dur?: number; all?: boolean }, label: string) => void

/**
 * The transitions. With a cut picked (its dot on the timeline) a tile changes
 * that cut; with none (no shot numbers), every cut, shown on the first two shots.
 */
export function Transitions({ join, before, after, from, to, onPick }: {
  join: JoinInfo; before: number | null; after: number | null; from: string | null; to: string | null; onPick: JoinPick
}) {
  const one = before != null && after != null
  const m = useLoop(1.8)
  const picked = join.picked ?? null
  const dur = join.picked_dur ?? 0.5
  const where = one ? `the cut from shot ${before} to shot ${after}` : 'every cut'
  const current = one ? (picked ?? join.picture) : (join.picked_all ? picked : null)
  // a blend picked here that the footage can't give (no film past the cut) plays as a cut
  const short = one && !!picked && picked !== 'cut' && picked !== join.picture && !['dip_black', 'flash'].includes(picked)
  return (
    <div className="flex flex-col gap-3">
      <div className={GRID}>
        {Object.entries(TRANSITION_NAMES).map(([id, name]) => (
          <Tile key={id} on={current === id} label={name}
                onClick={() => onPick({ kind: id, dur, ...(one ? {} : { all: true }) }, one ? `${name} at ${where}` : `Every cut is now a ${name.toLowerCase()}`)}>
            <JoinSample kind={id} from={from} to={to} m={m} />
          </Tile>
        ))}
      </div>
      {short && <p className="font-serif text-[15px] text-zinc-100">
        These shots weren't filmed long enough past the cut to blend, so this one stays a cut.</p>}
      <Slider label="Length" value={dur} min={0.2} max={1.5} step={0.1} unit=" s" disabled={!picked || picked === 'cut'}
              onCommit={(v) => picked && onPick({ kind: picked, dur: v, ...(one ? {} : { all: true }) }, `The ${TRANSITION_NAMES[picked].toLowerCase()} now takes ${v} s`)} />
      <div className="flex flex-wrap gap-2">
        {one && <Chip onClick={() => onPick({ kind: picked ?? join.picture, dur, all: true },
          `Every cut is now a ${TRANSITION_NAMES[picked ?? join.picture].toLowerCase()}`)}>Use for every cut</Chip>}
        {picked && <Chip onClick={() => join.picked_all || !one
          ? onPick({ kind: 'auto', all: true }, 'Every cut is back to the look\'s own')
          : onPick({ kind: 'auto' }, `${where[0].toUpperCase()}${where.slice(1)} is back to the look's own`)}>
          Back to the look's own</Chip>}
      </div>
    </div>
  )
}
