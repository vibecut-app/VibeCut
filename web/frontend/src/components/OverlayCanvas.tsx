import { useEffect, useRef, useState } from 'react'
import { drawOverlays, ensureFonts, safe, typeLook, type OverlayBox, type Part, type TypeLine, type TypeLook } from '../overlayDraw'
import { phStore } from '../transport'
import { multiline, typable, wordsOf, wordsPatch } from '../captionWords'
import type { Overlay, OverlayPlace, OverlayStyle } from '../types'
import { drawGraphics, ensureGraphicFonts } from '../graphicDraw'
import type { Graphic } from '../types'

// the graphic animations ride along: drawn under the words, picked and
// dragged the same way (a caption on top wins the click)
export type OverlayView = { items: Overlay[]; style: OverlayStyle; parts: Part[]; graphics?: Graphic[] }

// Moving words by hand on the picture: pick one, drag it, drag a corner to
// size it. Each drop is one undoable edit; export draws the same place.
// Clicking a picked caption again types into it right there (sarah,
// 2026-10-18: edit the words on screen, not in the side panel).
export type OverlayEdit = {
  selected: string | null
  onSelect: (id: string | null) => void
  onPlace: (id: string, place: OverlayPlace | null) => void
  onPlaceAll: (place: OverlayPlace) => void
  onOpen: (id: string) => void
  onWords: (id: string, patch: { text?: string; sub?: string }) => void
  /** one line of a group picked on its own (a title and the line under it): null = the whole group */
  line: LineRole | null
  onLine: (role: LineRole | null) => void
  /** a picked line dragged away from its group: its nudge, one undoable edit */
  onNudge: (id: string, role: LineRole, look: LineLook) => void
}

const SNAP = 0.02   // pulls onto the centre lines within 2% of the frame
type LineRole = import('../types').LineRole
type LineLook = import('../types').LineLook
type Drag = { id: string; mode: 'move' | 'scale' | 'line'; role?: LineRole; nudge0?: { dx: number; dy: number }; x0: number; y0: number; start: OverlayPlace; d0: number; moved: boolean; again: boolean }
// the box being typed into: where the caption was drawn when typing began
type Typing = { id: string; box: OverlayBox; value: string }
type Guides = { v: boolean; h: boolean } | null

// The live preview of words on screen: the same drawOverlays the export
// uses, redrawn whenever the playhead moves. Sized to the stage in device
// pixels; the composition scales with it, so it matches the export frame.
export function OverlayCanvas({ view, width, height, edit }: { view: OverlayView; width: number; height: number; edit?: OverlayEdit }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const gref = useRef<HTMLCanvasElement>(null)
  const boxes = useRef<OverlayBox[]>([])
  const [drag, setDrag] = useState<Drag | null>(null)
  const [live, setLive] = useState<{ id: string; place: OverlayPlace } | null>(null)
  const [liveLine, setLiveLine] = useState<{ id: string; role: LineRole; dx: number; dy: number } | null>(null)
  const [guides, setGuides] = useState<Guides>(null)
  const [selBox, setSelBox] = useState<OverlayBox | null>(null)
  const [typing, setTyping] = useState<Typing | null>(null)
  // read by the box's blur, which can come after Enter already saved it
  const typingRef = useRef<Typing | null>(null)
  typingRef.current = typing
  const placed: OverlayView = live
    ? { ...view, items: view.items.map((o) => (o.id === live.id ? { ...o, place: live.place } : o)),
        graphics: view.graphics?.map((g) => (g.id === live.id ? { ...g, place: live.place, size: live.place.scale } : g)) }
    : view
  // the words being typed stand in for the drawn ones until they're saved
  const shown: OverlayView = typing ? { ...placed, items: placed.items.filter((o) => o.id !== typing.id) } : placed
  // a line of a group being dragged away from the rest
  const drawn: OverlayView = liveLine ? { ...shown, items: shown.items.map((o) => o.id !== liveLine.id ? o
    : { ...o, lines: { ...o.lines, [liveLine.role]: { ...o.lines?.[liveLine.role], dx: liveLine.dx, dy: liveLine.dy } } }) } : shown
  const viewRef = useRef(drawn)
  viewRef.current = drawn
  const selRef = useRef(edit?.selected ?? null)
  selRef.current = edit?.selected ?? null

  useEffect(() => {
    const c = ref.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1
    const gc = gref.current
    for (const k of gc ? [c, gc] : [c]) {
      k.width = Math.max(1, Math.round(width * dpr))
      k.height = Math.max(1, Math.round(height * dpr))
    }
    const ctx = c.getContext('2d')!
    const gctx = gc?.getContext('2d') ?? null
    let raf = 0
    const draw = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const v = viewRef.current
        const out: OverlayBox[] = []
        if (gctx) {
          gctx.clearRect(0, 0, c.width, c.height)
          drawGraphics(gctx, c.width, c.height, v.graphics ?? [], phStore.get(), out)
        }
        drawOverlays(ctx, c.width, c.height, v.items, v.style, v.parts, phStore.get(), out)
        const css = <T extends { x: number; y: number; w: number; h: number }>(b: T): T => ({ ...b, x: b.x / dpr, y: b.y / dpr, w: b.w / dpr, h: b.h / dpr })
        boxes.current = out.map((b) => ({ ...css(b), rows: b.rows?.map(css) }))
        const s = boxes.current.find((b) => b.id === selRef.current) ?? null
        const near = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
          Math.abs(a.x - b.x) + Math.abs(a.y - b.y) + Math.abs(a.w - b.w) + Math.abs(a.h - b.h) < 0.5
        setSelBox((old) => (old && s && old.id === s.id && near(old, s) && (old.rows ?? []).length === (s.rows ?? []).length
          && (old.rows ?? []).every((r, i) => near(r, s.rows![i])) ? old : s))
      })
    }
    draw()
    let alive = true
    ensureFonts(shown.style).then(() => { if (alive) draw() })
    if (shown.graphics?.length) ensureGraphicFonts().then(() => { if (alive) draw() })
    const off = phStore.subscribe(draw)
    return () => { alive = false; off(); cancelAnimationFrame(raf) }
  }, [width, height, drawn, edit?.selected]) // eslint-disable-line react-hooks/exhaustive-deps

  // A fresh edit from the server (the music being picked polls the session
  // every 1.5 s) must not snap a caption back from under the pointer, nor
  // lose the drop: only a finished drag lets the server's place take over.
  const dragging = useRef(false)
  const lastPlace = useRef<OverlayPlace | null>(null)
  useEffect(() => { if (!dragging.current) { setLive(null); setLiveLine(null) } }, [view])

  const placeOf = (id: string): OverlayPlace => {
    const o = view.items.find((x) => x.id === id)
    if (o?.place) return o.place
    // a graphic's size is its own, so a drag keeps it
    const g = view.graphics?.find((x) => x.id === id)
    if (g?.place) return { ...g.place, scale: g.size ?? 1 }
    const b = boxes.current.find((x) => x.id === id)
    const sc = g?.size ?? 1
    return b ? { x: (b.x + b.w / 2) / width, y: (b.y + b.h / 2) / height, scale: sc } : { x: 0.5, y: 0.5, scale: sc }
  }
  const local = (e: React.PointerEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const hit = (x: number, y: number) =>
    [...boxes.current].reverse().find((b) => x >= b.x - 6 && x <= b.x + b.w + 6 && y >= b.y - 6 && y <= b.y + b.h + 6) ?? null
  // which corner handle (0 tl, 1 tr, 2 bl, 3 br) is under the pointer, or -1;
  // the handles are drawn 4 px outside the box
  const cornerAt = (x: number, y: number) => !selBox ? -1
    : [[selBox.x - 4, selBox.y - 4], [selBox.x + selBox.w + 4, selBox.y - 4], [selBox.x - 4, selBox.y + selBox.h + 4],
      [selBox.x + selBox.w + 4, selBox.y + selBox.h + 4]]
      .findIndex(([cx, cy]) => Math.abs(x - cx) <= 10 && Math.abs(y - cy) <= 10)
  const onCorner = (x: number, y: number) => cornerAt(x, y) >= 0

  // a different caption picked (or none) ends typing without saving
  useEffect(() => { if (typing && edit?.selected !== typing.id) setTyping(null) }, [edit?.selected]) // eslint-disable-line react-hooks/exhaustive-deps

  const art = !!view.graphics?.length && <canvas ref={gref} className="pointer-events-none absolute inset-0 z-[5] size-full" aria-hidden="true" />
  if (!edit) return <>{art}<canvas ref={ref} className="pointer-events-none absolute inset-0 z-[5] size-full" aria-hidden="true" /></>

  const pickedRow = edit.line && selBox ? selBox.rows?.find((r) => r.role === edit.line) ?? null : null
  const startTyping = (id: string) => {
    const o = view.items.find((x) => x.id === id)
    const b = boxes.current.find((x) => x.id === id)
    if (!o || !b || !typable(o)) return
    setTyping({ id, box: b, value: wordsOf(o) })
  }
  const stopTyping = (save: boolean) => {
    const t = typingRef.current
    if (!t) return
    typingRef.current = null
    const o = view.items.find((x) => x.id === t.id)
    const patch = save && o ? wordsPatch(o, t.value) : null
    setTyping(null)
    if (patch) edit.onWords(t.id, patch)
  }

  // the line of a group under the pointer, when the group is the one picked
  const rowAt = (b: OverlayBox, x: number, y: number) => {
    const rows = b.rows ?? []
    if (new Set(rows.map((r) => r.role)).size < 2) return null
    return rows.find((r) => x >= r.x - 4 && x <= r.x + r.w + 4 && y >= r.y - 3 && y <= r.y + r.h + 3) ?? null
  }
  const down = (e: React.PointerEvent) => {
    const p = local(e)
    const scaling = !edit.line && onCorner(p.x, p.y)
    const b = scaling ? selBox : hit(p.x, p.y)
    if (!b) { if (edit.selected) { edit.onSelect(null); e.stopPropagation() } return }
    e.stopPropagation()
    // A group picked already: a click on one of its lines picks that line
    // (CapCut's grouped text), a click on the picked line types into it, and
    // dragging a picked line moves it away from the rest of the group.
    const row = !scaling && edit.selected === b.id ? rowAt(b, p.x, p.y) : null
    if (row) {
      const o = view.items.find((x) => x.id === b.id)
      const L = o?.lines?.[row.role]
      if (edit.line !== row.role) edit.onLine(row.role)
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
      dragging.current = true
      setDrag({ id: b.id, mode: 'line', role: row.role, nudge0: { dx: L?.dx ?? 0, dy: L?.dy ?? 0 }, x0: p.x, y0: p.y,
        start: placeOf(b.id), d0: 1, moved: false, again: edit.line === row.role && typing?.id !== b.id })
      return
    }
    if (edit.selected !== b.id) edit.onSelect(b.id)
    else if (edit.line) edit.onLine(null)
    const start = placeOf(b.id)
    const cx = start.x * width, cy = start.y * height
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    dragging.current = true
    lastPlace.current = null
    setDrag({ id: b.id, mode: scaling ? 'scale' : 'move', x0: p.x, y0: p.y, start, d0: Math.max(8, Math.hypot(p.x - cx, p.y - cy)), moved: false,
      again: !scaling && edit.selected === b.id && typing?.id !== b.id })
  }
  const move = (e: React.PointerEvent) => {
    if (!drag) {
      const p = local(e)
      const k = cornerAt(p.x, p.y)
      ;(e.currentTarget as HTMLElement).style.cursor = k === 0 || k === 3 ? 'nwse-resize' : k > 0 ? 'nesw-resize'
        : hit(p.x, p.y) ? 'move' : 'default'
      return
    }
    const p = local(e)
    if (drag.mode === 'line') {
      // in shares of the frame's short side, at the group's own size
      const u = Math.min(width, height) * (drag.start.scale || 1)
      const dx = drag.nudge0!.dx + (p.x - drag.x0) / u, dy = drag.nudge0!.dy + (p.y - drag.y0) / u
      if (!drag.moved && Math.hypot(p.x - drag.x0, p.y - drag.y0) > 3) setDrag({ ...drag, moved: true })
      setLiveLine({ id: drag.id, role: drag.role!, dx: Math.max(-1, Math.min(1, dx)), dy: Math.max(-1, Math.min(1, dy)) })
      return
    }
    let place: OverlayPlace
    if (drag.mode === 'move') {
      let x = drag.start.x + (p.x - drag.x0) / width
      let y = drag.start.y + (p.y - drag.y0) / height
      const v = Math.abs(x - 0.5) < SNAP, h = Math.abs(y - 0.5) < SNAP
      if (v) x = 0.5
      if (h) y = 0.5
      x = Math.min(1, Math.max(0, x)); y = Math.min(1, Math.max(0, y))
      setGuides({ v, h })
      place = { ...drag.start, x, y }
    } else {
      const cx = drag.start.x * width, cy = drag.start.y * height
      const k = Math.hypot(p.x - cx, p.y - cy) / drag.d0
      place = { ...drag.start, scale: Math.min(3, Math.max(0.4, drag.start.scale * k)) }
      setGuides(null)
    }
    if (!drag.moved && Math.hypot(p.x - drag.x0, p.y - drag.y0) > 3) setDrag({ ...drag, moved: true })
    lastPlace.current = place
    setLive({ id: drag.id, place })
  }
  const up = () => {
    dragging.current = false
    if (drag?.mode === 'line') {
      if (drag.moved && liveLine) edit.onNudge(drag.id, drag.role!, { dx: Math.round(liveLine.dx * 1e4) / 1e4, dy: Math.round(liveLine.dy * 1e4) / 1e4 })
      else setLiveLine(null)
      setDrag(null)
      if (!drag.moved && drag.again) startTyping(drag.id)
      return
    }
    if (drag?.moved && lastPlace.current) edit.onPlace(drag.id, lastPlace.current)
    setDrag(null)
    setGuides(null)
    // keep showing the dropped place until the edit comes back
    if (!drag?.moved) setLive(null)
    // a click (no drag) on the caption already picked: type into it
    if (drag && !drag.moved && drag.again) startTyping(drag.id)
  }
  const sel = edit.selected ? view.items.find((o) => o.id === edit.selected) : null
  const selArt = edit.selected && !sel ? view.graphics?.find((g) => g.id === edit.selected) : null
  return (
    <>
      {art}
      <canvas ref={ref} className="pointer-events-none absolute inset-0 z-[5] size-full" aria-hidden="true" />
      <div className="absolute inset-0 z-[6]" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
           onDoubleClick={(e) => { const p = local(e as unknown as React.PointerEvent); const b = hit(p.x, p.y); if (b) { e.stopPropagation(); edit.onOpen(b.id); startTyping(b.id) } }}
           onClick={(e) => { if (drag || selBox) e.stopPropagation() }}>
        {guides?.v && <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-accent/80" />}
        {guides?.h && <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-accent/80" />}
        {selBox && pickedRow && (
          // the line picked inside its group: solid; the group around it dashed
          <div className="pointer-events-none absolute rounded-sm outline outline-2 outline-accent"
               style={{ left: pickedRow.x - 3, top: pickedRow.y - 2, width: pickedRow.w + 6, height: pickedRow.h + 4 }} />
        )}
        {selBox && (
          <div className={`pointer-events-none absolute rounded-sm outline outline-1 outline-accent ${pickedRow ? 'outline-dashed opacity-70' : ''}`}
               style={{ left: selBox.x - 4, top: selBox.y - 4, width: selBox.w + 8, height: selBox.h + 8 }}>
            {!pickedRow && (['-left-1.5 -top-1.5', '-right-1.5 -top-1.5', '-left-1.5 -bottom-1.5', '-right-1.5 -bottom-1.5'] as const).map((c) => (
              <i key={c} className={`absolute block size-2.5 rounded-sm border border-accent bg-zinc-900 ${c}`} />
            ))}
          </div>
        )}
        {typing && sel && <TypeBox key={typing.id} typing={typing} lines={multiline(sel)} width={width} height={height}
                                   look={typeLook(sel, view.style, Math.min(width, height))}
                                   onChange={(value) => setTyping((t) => (t ? { ...t, value } : t))}
                                   onDone={stopTyping} />}
        {selBox && selArt?.place && !drag && (
          <div className="absolute text-[10px]" onPointerDown={(e) => e.stopPropagation()}
               style={{ left: Math.max(4, Math.min(selBox.x, width - 80)), ...(selBox.y > 64 ? { bottom: height - selBox.y + 8 } : { top: selBox.y + selBox.h + 8 }) }}>
            <button type="button" onClick={(e) => { e.stopPropagation(); edit.onPlace(selArt.id, null) }}
                    className="rounded bg-zinc-900/90 px-2 py-1 text-zinc-300 ring-1 ring-line hover:bg-zinc-800">Reset</button>
          </div>
        )}
        {selBox && sel && !drag && !typing && (
          <div className="absolute flex flex-wrap gap-1 whitespace-nowrap text-[10px]"
               // on a narrow (vertical) frame the buttons wrap rather than run off it
               style={{ left: Math.max(4, Math.min(selBox.x, width - 290)), maxWidth: width - 8,
                 ...(selBox.y > 64 ? { bottom: height - selBox.y + 8 } : { top: selBox.y + selBox.h + 8 }) }}
               onPointerDown={(e) => e.stopPropagation()}>
            {typable(sel) && (
              <button type="button" onClick={(e) => { e.stopPropagation(); startTyping(sel.id) }}
                      className="rounded bg-zinc-900/90 px-2 py-1 text-zinc-100 ring-1 ring-line hover:bg-zinc-800">Edit words</button>
            )}
            {sel.kind === 'caption' && (
              <button type="button" onClick={(e) => { e.stopPropagation(); edit.onPlaceAll(placeOf(sel.id)) }}
                      className="rounded bg-zinc-900/90 px-2 py-1 text-zinc-100 ring-1 ring-line hover:bg-zinc-800">Same place for all captions</button>
            )}
            {sel.place && (
              <button type="button" onClick={(e) => { e.stopPropagation(); edit.onPlace(sel.id, null) }}
                      className="rounded bg-zinc-900/90 px-2 py-1 text-zinc-300 ring-1 ring-line hover:bg-zinc-800">Reset</button>
            )}
          </div>
        )}
      </div>
    </>
  )
}

// Typing on the picture, in the caption's own look (sarah, 2026-10-18: "keep
// the same font so I can visualize how it looks while editing the words"):
// each line is dressed as the canvas draws it, the place name small above,
// edge, backing and colour included. Enter starts a new line where there can
// be one; clicking away or Cmd/Ctrl+Enter saves (one undoable edit), Escape
// leaves the words as they were.
function TypeBox({ typing, lines, width, height, look, onChange, onDone }: {
  typing: Typing; lines: boolean; width: number; height: number; look: TypeLook
  onChange: (v: string) => void; onDone: (save: boolean) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const lookRef = useRef(look)
  lookRef.current = look
  const read = () => Array.from(ref.current?.children ?? []).map((c) => (c.textContent ?? '').replace(/\n/g, ' ')).join('\n')
  // a line's look depends on how many lines there are (one line = the
  // caption's words; two = the place name above, or a second line below)
  const dress = () => {
    const ed = ref.current
    if (!ed) return
    // stray text typed straight into the box goes into a line of its own
    const sel = window.getSelection()
    for (const n of Array.from(ed.childNodes)) {
      if (n.nodeType === Node.ELEMENT_NODE && (n as Element).tagName === 'DIV') continue
      const at = sel?.anchorNode === n ? sel.anchorOffset : -1
      const d = document.createElement('div')
      ed.insertBefore(d, n)
      d.appendChild(n)
      if (at >= 0) sel?.collapse(n, at)   // keep the caret where it was
    }
    const rows = Array.from(ed.children) as HTMLElement[]
    const { lead, main, trail } = lookRef.current
    rows.forEach((r, i) => {
      const ln = rows.length > 1 && lead && i === 0 ? lead : rows.length > 1 && trail && i > 0 ? trail : main
      dressLine(r, ln)
    })
  }
  useEffect(() => {
    const ed = ref.current
    if (!ed) return
    for (const line of typing.value.split('\n')) {
      const d = document.createElement('div')
      if (line) d.textContent = line
      else d.appendChild(document.createElement('br'))
      ed.appendChild(d)
    }
    dress()
    ed.focus()
    // the caret at the end of the words, nothing selected
    const r = document.createRange()
    r.selectNodeContents(ed)
    r.collapse(false)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(r)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(dress, [look]) // eslint-disable-line react-hooks/exhaustive-deps

  const { box } = typing
  const m = safe(width, height)
  return (
    <div ref={ref} contentEditable suppressContentEditableWarning role="textbox" aria-multiline={lines} aria-label="Caption words"
         spellCheck={false}
         onInput={() => { dress(); onChange(read()) }}
         onBlur={() => onDone(true)}
         onPaste={(e) => { e.preventDefault(); document.execCommand('insertText', false, e.clipboardData.getData('text/plain').replace(/\n/g, lines ? '\n' : ' ')) }}
         onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
         onKeyDown={(e) => {
           e.stopPropagation()   // typing must not split shots or play the video
           if (e.key === 'Enter' && (!lines || e.metaKey || e.ctrlKey)) { e.preventDefault(); onDone(true) }
           if (e.key === 'Escape') { e.preventDefault(); onDone(false) }
         }}
         className={`absolute -translate-y-1/2 cursor-text whitespace-pre-wrap break-words rounded outline-dashed outline-1 outline-offset-4 outline-white/70 ${look.align === 'left' ? 'text-left' : '-translate-x-1/2 text-center'}`}
         style={{ left: look.align === 'left' ? box.x : box.x + box.w / 2, top: box.y + box.h / 2, width: 'max-content', minWidth: 40,
           maxWidth: Math.max(80, width - m.l - m.r), background: look.backing ?? undefined,
           padding: look.backing ? '0.3em 0.6em' : 0, caretColor: look.main.color }} />
  )
}

// one typed line, dressed the way the canvas draws it
function dressLine(el: HTMLElement, ln: TypeLine) {
  const st = el.style
  st.font = ln.font
  st.lineHeight = String(ln.lh)
  st.color = ln.color
  st.letterSpacing = `${ln.track}px`
  st.textTransform = ln.upper ? 'uppercase' : ln.lower ? 'lowercase' : 'none'
  st.textShadow = ln.shadow
  st.setProperty('-webkit-text-stroke', ln.stroke ? `${ln.stroke.w}px ${ln.stroke.color}` : '0')
  st.setProperty('paint-order', 'stroke fill')
  st.background = ln.band?.fill ?? 'none'
  st.borderRadius = ln.band ? `${ln.band.radius}px` : '0'
  st.padding = ln.band ? `0 ${ln.band.padX}px` : '0'
  st.width = ln.band ? 'fit-content' : 'auto'
  st.marginInline = ln.band ? 'auto' : '0'
  st.marginBlock = ln.band ? `${ln.px * 0.12}px` : '0'
}
