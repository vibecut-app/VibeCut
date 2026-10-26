import { useEffect, useRef, useState } from 'react'
import { drawGraphics, ensureGraphicFonts, FRAMEWIDE, HAS_WORDS, PIECE_ORDER, PIECES, STICKER_NAMES, tilePiece } from '../graphicDraw'
import { useLoop } from '../styleNames'
import type { Graphic, GraphicPiece, Graphics as GraphicsData, StickerKind } from '../types'
import { cx } from '../ui'
import { Icon } from './icons'
import { Chip, SaveChip, Slider } from './Inspector'
import { Tile } from './StyleBars'

// The Graphic animations tab (sarah, 2026-10-19: "make it an extra tool on
// the right called graphic animations"). A gallery of pieces, each tile
// playing on a frame of the video the way it will play in it (graphicDraw,
// the same code as the preview and the export); one click puts it on at the
// playhead as one undoable turn, and nothing is on until something is picked.
// A clicked graphic (on the picture, the timeline or the list here) shows its
// own words, sticker, colour, size, length and place above the gallery.

const TILE_W = 112, TILE_H = 76
const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] justify-items-center gap-x-2 gap-y-3'
// the words each piece carries, by what they are on the picture
const WORDS: Partial<Record<GraphicPiece, [string, string?]>> = {
  title: ['Title', 'Line above'], chapter: ['Name', 'Number'], pin: ['Place'], camcorder: ['Date'],
  clock: ['Words under'], circle: ['Words beside'],
}
// soft colours, like a quiet vlog's (every piece's own colour is one of them)
const COLOURS: [string, string][] = [['#ffffff', 'White'], ['#f6ead7', 'Cream'], ['#ffe08a', 'Butter'], ['#e8b4b8', 'Blush'],
  ['#c97b84', 'Dusty rose'], ['#c96f58', 'Terracotta'], ['#a8c3a0', 'Sage'], ['#a9c8e0', 'Sky blue'], ['#b9a8d6', 'Lavender'], ['#141414', 'Black']]
const STICKERS = Object.keys(STICKER_NAMES) as StickerKind[]
export type GraphicPatch = Partial<Pick<Graphic, 'text' | 'sub' | 'tint' | 'sticker' | 'size' | 'dur' | 'place'>>

export function GraphicAnimations({ data, selected, thumb, onAdd, onSelect, onEdit, onDelete, onWatch, saveReady, onSave }: {
  data: GraphicsData | null
  /** the graphic clicked on the picture, the timeline or the list */
  selected: Graphic | null
  /** a frame of the video, for the tiles to play on */
  thumb: string | null
  onAdd: (piece: GraphicPiece) => void
  onSelect: (id: string | null) => void
  onEdit: (patch: GraphicPatch, label: string) => void
  onDelete: () => void
  onWatch: () => void
  saveReady: boolean
  onSave: () => void
}) {
  // one clock for every tile: each plays its piece round and round
  const secs = useLoop(240) * 240
  const [why, setWhy] = useState<GraphicPiece | null>(null)
  const can = data?.can
  const items = data?.items ?? []
  const bg = thumb ? { backgroundImage: `url(${thumb})`, backgroundSize: 'cover', backgroundPosition: 'center' } : undefined
  useEffect(() => { ensureGraphicFonts() }, [])
  return (
    <>
      {selected && <Picked key={selected.id} g={selected} onEdit={onEdit} onDelete={onDelete} onWatch={onWatch}
                           onDone={() => onSelect(null)} saveReady={saveReady} onSave={onSave} />}
      {!selected && items.length > 0 && (
        <section className="space-y-2">
          <h3 className="font-serif text-[18px] font-medium text-zinc-100">On your video</h3>
          <ul className="space-y-1.5">
            {items.map((g) => (
              <li key={g.id}>
                <button type="button" onClick={() => onSelect(g.id)}
                        className="flex w-full items-center gap-3 rounded-xl border border-line bg-panel px-2 py-1.5 text-left hover:bg-raised">
                  <Still g={g} size={40} />
                  <span className="min-w-0 flex-1 truncate font-serif text-[16px] text-zinc-100">{PIECES[g.piece].name}{g.text ? ` · ${g.text}` : ''}</span>
                  <span className="shrink-0 font-serif text-[15px] tabular-nums text-zinc-300">{clock(g.start)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="space-y-3">
        <h3 className="font-serif text-[18px] font-medium text-zinc-100">{items.length ? 'Add another at the playhead' : 'Add one at the playhead'}</h3>
        <div className={GRID}>
          {PIECE_ORDER.map((piece) => {
            const no = can?.[piece] ?? null
            return (
              <div key={piece} className={cx(no && 'opacity-45')} title={no ?? PIECES[piece].line}>
                <Tile on={false} label={PIECES[piece].name} onClick={() => { if (no) setWhy(piece); else { setWhy(null); onAdd(piece) } }}>
                  <span className="absolute inset-0" style={bg} />
                  <span className="absolute inset-0 bg-black/15" />
                  <Sample piece={piece} t={secs % (PIECES[piece].life + 0.7)} />
                </Tile>
              </div>
            )
          })}
        </div>
        {why && can?.[why]
          ? <p role="status" className="rounded-lg bg-raised px-3 py-2 font-serif text-[15px] leading-snug text-zinc-100">{PIECES[why].name}: {can[why]}.</p>
          : <p className="font-serif text-[15px] leading-snug text-zinc-300">Drag one on the picture to move it, or a corner to size it.</p>}
      </section>
    </>
  )
}

/** A piece on a tile, at `t` seconds into it, as the video will show it. */
function Sample({ piece, t, sticker, tint }: { piece: GraphicPiece; t: number; sticker?: StickerKind; tint?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current
    const ctx = c?.getContext('2d')
    if (!c || !ctx) return
    ctx.clearRect(0, 0, c.width, c.height)
    drawGraphics(ctx, c.width, c.height, [tilePiece(piece, 1, tint, sticker)], t)
  }, [piece, t, sticker, tint])
  return <canvas ref={ref} width={TILE_W * 2} height={TILE_H * 2} className="absolute inset-0 size-full" />
}

/** A graphic held still once it's in, for lists. */
function Still({ g, size }: { g: Pick<Graphic, 'piece' | 'tint' | 'sticker'> & Partial<Pick<Graphic, 'text' | 'sub'>>; size: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    let alive = true
    const draw = () => {
      const c = ref.current
      const ctx = c?.getContext('2d')
      if (!c || !ctx || !alive) return
      ctx.clearRect(0, 0, c.width, c.height)
      // a square: a little bigger again than on a wide tile
      // its own words where it has them
      const shown = { ...tilePiece(g.piece, 1.35, g.tint, g.sticker), ...(g.text ? { text: g.text, sub: g.sub ?? '' } : {}) }
      drawGraphics(ctx, c.width, c.height, [shown], PIECES[g.piece].life * 0.55)
    }
    draw()
    ensureGraphicFonts().then(draw)
    return () => { alive = false }
  }, [g.piece, g.tint, g.sticker, g.text, g.sub])
  return <canvas ref={ref} width={size * 2} height={size * 2} className="shrink-0 rounded-lg bg-[#3a3f47]" style={{ width: size, height: size }} />
}

// The clicked graphic: its words, sticker, colour, size, length and place.
// Each change is one undoable turn, sent when a box is left or a slider let go.
function Picked({ g, onEdit, onDelete, onWatch, onDone, saveReady, onSave }: {
  g: Graphic; onEdit: (patch: GraphicPatch, label: string) => void
  onDelete: () => void; onWatch: () => void; onDone: () => void; saveReady: boolean; onSave: () => void
}) {
  const name = PIECES[g.piece].name
  const lower = name.toLowerCase()
  const words = HAS_WORDS[g.piece] ? WORDS[g.piece] : undefined
  const wide = FRAMEWIDE.includes(g.piece)
  const row = !g.place ? 'usual' : g.place.y < 0.35 ? 'top' : g.place.y > 0.65 ? 'bottom' : 'middle'
  const size = g.size ?? 1
  return (
    <section className="space-y-3">
      <h3 className="font-serif text-[18px] font-medium text-zinc-100">{name} · {clock(g.start)}</h3>
      <div><SaveChip what="graphic animation" ready={saveReady} onClick={onSave} /></div>
      {words?.map((label, i) => {
        const key = i === 0 ? 'text' : 'sub'
        const value = (i === 0 ? g.text : g.sub) ?? ''
        return (
          <Row key={key} label={label!}>
            <WordsLine key={value} value={value} label={label!}
                       onCommit={(v) => onEdit({ [key]: v }, `You changed the words of the ${lower}`)} />
          </Row>
        )
      })}
      {g.piece === 'stickers' && (
        <div className="grid grid-cols-4 gap-2">
          {STICKERS.map((k) => (
            <button key={k} type="button" title={STICKER_NAMES[k]} aria-label={STICKER_NAMES[k]} aria-pressed={g.sticker === k}
                    onClick={() => g.sticker !== k && onEdit({ sticker: k }, `The sticker is now a ${STICKER_NAMES[k].toLowerCase()}`)}
                    className={cx('relative flex aspect-square items-center justify-center overflow-hidden rounded-xl border-[3px] bg-[#3a3f47]',
                      g.sticker === k ? 'border-accent' : 'border-transparent hover:border-zinc-500')}>
              <Still g={{ piece: 'stickers', tint: g.tint, sticker: k }} size={56} />
            </button>
          ))}
        </div>
      )}
      <Row label="Colour">
        <Colours value={g.tint} onPick={(c) => onEdit({ tint: c }, `You changed the colour of the ${lower}`)} />
      </Row>
      {!wide && (
        <Slider label="Size" value={Math.round(size * 100)} min={40} max={300} step={10} unit="%"
                onCommit={(v) => onEdit({ size: v / 100 }, `You made the ${lower} ${v > size * 100 ? 'bigger' : 'smaller'}`)} />
      )}
      {g.dur != null && (
        <Slider label="Length" value={g.dur} min={1} max={10} step={0.5} unit=" s"
                onCommit={(v) => onEdit({ dur: v }, `You made the ${lower} ${v > g.dur! ? 'longer' : 'shorter'}`)} />
      )}
      {g.dur == null && (
        <p className="font-serif text-[15px] leading-snug text-zinc-300">
          {g.piece === 'progress' ? 'It runs for the whole video.' : 'It runs to the end of this part. Drag its end on the timeline to stop it sooner.'}
        </p>
      )}
      {!wide && (
        <Row label="Place">
          <div className="flex flex-1 rounded-lg bg-raised p-0.5">
            {([['usual', 'Usual'], ['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={row === id}
                      onClick={() => row !== id && onEdit({ place: id === 'usual' ? null : { x: 0.5, y: id === 'top' ? 0.2 : id === 'middle' ? 0.5 : 0.8, scale: 1 } },
                        id === 'usual' ? `You put the ${lower} back in its usual place` : `You moved the ${lower} to the ${id}`)}
                      className={cx('flex-1 rounded-md px-2 py-1.5 font-serif text-[15px]',
                        row === id ? 'bg-panel text-accent shadow-sm' : 'text-zinc-300 hover:text-zinc-100')}>{label}</button>
            ))}
          </div>
        </Row>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <Chip onClick={onWatch}><Icon name="play" size={17} /> See it play</Chip>
        <Chip danger onClick={onDelete}><Icon name="trash" size={17} /> Delete</Chip>
        <Chip onClick={onDone}>Done</Chip>
      </div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 font-serif text-[16px] text-zinc-100">{label}</span>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
    </div>
  )
}

function WordsLine({ value, label, onCommit }: { value: string; label: string; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value)   // keyed on value by the caller: a new value remounts
  return (
    <input value={v} maxLength={80} aria-label={label} onChange={(e) => setV(e.target.value)}
           onBlur={() => v.trim() !== value && onCommit(v.trim())}
           onKeyDown={(e) => {
             e.stopPropagation()   // typing must not split shots or play the video
             if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur() }
             if (e.key === 'Escape') { setV(value); setTimeout(() => (e.target as HTMLInputElement).blur()) }
           }}
           className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 py-1.5 font-serif text-[16px] text-zinc-100 outline-none focus:border-accent" />
  )
}

// a row of swatches and any colour; the native picker reports once, when it closes
function Colours({ value, onPick }: { value: string; onPick: (c: string) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const pick = useRef(onPick)
  pick.current = onPick
  useEffect(() => {
    const el = ref.current
    const done = () => el && el.value !== value && pick.current(el.value)
    el?.addEventListener('change', done)
    return () => el?.removeEventListener('change', done)
  }, [value])
  const custom = !COLOURS.some(([c]) => c === value)
  return (
    <div className="flex flex-wrap items-center gap-2">
      {COLOURS.map(([c, name]) => (
        <button key={c} type="button" title={name} aria-label={name} aria-pressed={value === c} onClick={() => value !== c && onPick(c)}
                className={cx('size-8 shrink-0 rounded-full border border-black/15', value === c && 'ring-2 ring-accent ring-offset-2 ring-offset-panel')}
                style={{ background: c }} />
      ))}
      <label title="Any colour" aria-label="Any colour"
             className={cx('relative size-8 shrink-0 cursor-pointer rounded-full border border-black/15', custom && 'ring-2 ring-accent ring-offset-2 ring-offset-panel')}
             style={{ background: custom ? value : 'conic-gradient(#ff6b6b, #ffd84d, #8fe3b0, #7fd0ff, #c49bff, #ff6b6b)' }}>
        <input ref={ref} type="color" defaultValue={value} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
    </div>
  )
}

const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`
