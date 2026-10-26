// Graphic animations, drawn: every piece, in both frame shapes, once it's in
// keeps its words inside the safe area and every mark inside the frame; a long
// title shrinks or wraps rather than running off; a piece is a pure function
// of time (any frame, any order, same pixels), which is what lets the export
// render frames out of order; and the export's frame keys change while a
// piece moves and stay put while it holds, so one PNG serves a still run.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { drawGraphics, graphicFrames, graphicsKey, PIECE_ORDER, PIECES, samplePiece } from './graphicDraw.ts'
import { safe } from './overlayDraw.ts'
import type { Graphic, GraphicPiece } from './types'

type Pt = [number, number]
type Call = { op: string; pts: Pt[]; text?: string }

// A canvas that remembers where everything landed, through every transform.
function recorder() {
  let m = [1, 0, 0, 1, 0, 0]
  const stack: number[][] = []
  const calls: Call[] = []
  const at = (x: number, y: number): Pt => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]
  const note = (op: string, pts: Pt[], text?: string) => calls.push({ op, pts: pts.map(([x, y]) => at(x, y)), text })
  const state: Record<string, unknown> = { font: '10px x', letterSpacing: '0px', lineWidth: 1, textAlign: 'left', textBaseline: 'alphabetic' }
  const grad = { addColorStop() {} }
  const own: Record<string, (...a: number[]) => unknown> = {
    save: () => { stack.push([...m]) },
    restore: () => { m = stack.pop() ?? [1, 0, 0, 1, 0, 0] },
    translate: (x, y) => { m = [m[0], m[1], m[2], m[3], m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] },
    scale: (a, b) => { m = [m[0] * a, m[1] * a, m[2] * b, m[3] * b, m[4], m[5]] },
    rotate: (r) => {
      const c = Math.cos(r), s = Math.sin(r)
      m = [m[0] * c + m[2] * s, m[1] * c + m[3] * s, -m[0] * s + m[2] * c, -m[1] * s + m[3] * c, m[4], m[5]]
    },
    setTransform: (a, b, c, d, e, f) => { m = [a, b, c, d, e, f] },
    resetTransform: () => { m = [1, 0, 0, 1, 0, 0] },
    moveTo: (x, y) => note('path', [[x, y]]),
    lineTo: (x, y) => note('path', [[x, y]]),
    quadraticCurveTo: (cx, cy, x, y) => note('path', [[cx, cy], [x, y]]),
    bezierCurveTo: (a, b, c, d, x, y) => note('path', [[a, b], [c, d], [x, y]]),
    arc: (x, y, r) => note('path', [[x - r, y - r], [x + r, y + r]]),
    ellipse: (x, y, rx, ry) => { const r = Math.max(rx, ry); note('path', [[x - r, y - r], [x + r, y + r]]) },
    rect: (x, y, w, h) => note('path', [[x, y], [x + w, y + h]]),
    roundRect: (x, y, w, h) => note('path', [[x, y], [x + w, y + h]]),
    fillRect: (x, y, w, h) => note('rect', [[x, y], [x + w, y + h]]),
    strokeRect: (x, y, w, h) => note('rect', [[x, y], [x + w, y + h]]),
    measureText: () => ({ width: 0 }),
    createLinearGradient: () => grad,
    createRadialGradient: () => grad,
  }
  const ctx: Record<string, unknown> = new Proxy(state, {
    get(t, k: string) {
      if (k === 'measureText') return (s: string) => ({ width: s.length * px() * 0.56 + Math.max(0, s.length - 1) * ls() })
      if (k === 'fillText' || k === 'strokeText') {
        return (s: string, x: number, y: number) => {
          if (!s.trim()) return
          const w = s.length * px() * 0.56, h = px()
          const x0 = t.textAlign === 'center' ? x - w / 2 : t.textAlign === 'right' ? x - w : x
          const y0 = t.textBaseline === 'top' ? y : t.textBaseline === 'middle' ? y - h / 2 : t.textBaseline === 'bottom' ? y - h : y - h * 0.8
          note('text', [[x0, y0], [x0 + w, y0], [x0, y0 + h], [x0 + w, y0 + h]], s)
        }
      }
      if (k in own) return own[k]
      if (k in t) return t[k]
      return () => {}
    },
    set(t, k: string, v) { t[k] = v; return true },
    has: () => true,
  })
  const px = () => parseFloat(/(\d+(?:\.\d+)?)px/.exec(String(state.font))?.[1] ?? '10')
  const ls = () => parseFloat(String(state.letterSpacing)) || 0
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls }
}

const SHAPES: [string, number, number][] = [['vertical', 1080, 1920], ['wide', 1920, 1080]]
// the words a piece carries on a real video: a place, a part, a date
const dressed = (piece: GraphicPiece, extra: Partial<Graphic> = {}): Graphic => {
  const g = samplePiece(piece)
  const words: Partial<Record<GraphicPiece, Partial<Graphic>>> = {
    title: { text: 'Morningside Heights', sub: 'Sunday' }, chapter: { text: 'Coffee before class', sub: '02' },
    pin: { text: 'Columbia University' }, clock: { text: 'first coffee' }, circle: { text: 'this one!' },
    route: { stops: [{ x: 0, y: 1, name: 'Home' }, { x: 0.73, y: 0.89, name: null }, { x: 1, y: 0, name: 'Butler Library' }], here: 2, aspect: 1.4 },
  }
  return { ...g, ...words[piece], ...extra }
}
const draw = (g: Graphic, t: number, W: number, H: number) => {
  const r = recorder()
  drawGraphics(r.ctx, W, H, [g], t)
  return r.calls
}
// once in, before it leaves
const held = (piece: GraphicPiece) => [0.5, 0.55, 0.6].map((k) => k * PIECES[piece].life)

test('every piece keeps its words in the safe area and its marks in the frame, both shapes', () => {
  for (const [shape, W, H] of SHAPES) {
    const m = safe(W, H)
    for (const piece of PIECE_ORDER) {
      for (const t of held(piece)) {
        const calls = draw(dressed(piece), t, W, H)
        assert.ok(calls.length > 0, `${piece} draws something at ${t}s (${shape})`)
        for (const c of calls) {
          for (const [x, y] of c.pts) {
            assert.ok(x >= -1 && x <= W + 1 && y >= -1 && y <= H + 1, `${piece} ${shape} ${c.op} at (${x.toFixed(0)}, ${y.toFixed(0)}) is off the frame`)
            if (c.op !== 'text') continue
            assert.ok(x >= m.l - 2 && x <= W - m.r + 2 && y >= m.t - 2 && y <= H - m.b + 2,
              `${piece} ${shape}: “${c.text}” at (${x.toFixed(0)}, ${y.toFixed(0)}) is outside the safe area`)
          }
        }
      }
    }
  }
})

test('a long title shrinks or wraps instead of running off', () => {
  for (const [, W, H] of SHAPES) {
    const m = safe(W, H)
    const g = dressed('title', { text: 'A very long day of walking around the whole of lower Manhattan with friends', sub: 'October 19, 2026' })
    const texts = draw(g, 1.9, W, H).filter((c) => c.op === 'text')
    assert.ok(texts.length > 0)
    for (const c of texts) for (const [x] of c.pts) assert.ok(x >= m.l - 2 && x <= W - m.r + 2, `“${c.text}” runs to ${x.toFixed(0)}`)
  }
})

test('a piece is a pure function of time: any frame, any order, the same marks', () => {
  for (const piece of PIECE_ORDER) {
    const g = dressed(piece)
    const ts = [0.1, 0.4, 0.9, 1.6, 2.2, PIECES[piece].life - 0.1]
    const fwd = ts.map((t) => JSON.stringify(draw(g, t, 1080, 1920)))
    const back = [...ts].reverse().map((t) => JSON.stringify(draw(g, t, 1080, 1920))).reverse()
    assert.deepEqual(fwd, back, `${piece} drew differently out of order`)
  }
})

test('nothing is drawn outside its own seconds', () => {
  for (const piece of PIECE_ORDER) {
    const g = { ...dressed(piece), start: 10, end: 13, shown_end: 13 }
    assert.equal(draw(g, 9.99, 1080, 1920).length, 0, `${piece} before its start`)
    assert.equal(draw(g, 13, 1080, 1920).length, 0, `${piece} at its end`)
  }
})

test('placed by hand and made big, it still sits where it was put', () => {
  for (const piece of PIECE_ORDER.filter((p) => p !== 'camcorder' && p !== 'progress')) {
    const g = dressed(piece, { place: { x: 0.3, y: 0.7, scale: 1 }, size: 1.6 })
    const calls = draw(g, held(piece)[1], 1080, 1920)
    const pts = calls.flatMap((c) => c.pts)
    const cx = (Math.min(...pts.map((p) => p[0])) + Math.max(...pts.map((p) => p[0]))) / 2
    const cy = (Math.min(...pts.map((p) => p[1])) + Math.max(...pts.map((p) => p[1]))) / 2
    assert.ok(Math.abs(cx - 0.3 * 1080) < 0.25 * 1080 && Math.abs(cy - 0.7 * 1920) < 0.2 * 1920,
      `${piece} centred at (${cx.toFixed(0)}, ${cy.toFixed(0)}), put at (324, 1344)`)
  }
})

test('export keys move while a piece moves and hold while it holds', () => {
  const fps = 30
  for (const piece of PIECE_ORDER) {
    const g = dressed(piece)
    const intro = [0.1, 0.1 + 1 / fps].map((t) => graphicsKey([g], t, fps))
    assert.notEqual(intro[0], intro[1], `${piece}: the intro's frames share a key`)
    assert.equal(graphicsKey([g], g.shown_end + 0.01, fps), '', `${piece}: a key after it's gone`)
  }
  // the camcorder's clock only changes once a second (and its REC dot blinks)
  const cam = { ...dressed('camcorder'), start: 0, end: 20, shown_end: 20, dur: 20, times: [[0, 20, 9 * 3600, 1]] as [number, number, number, number][] }
  const keys = new Set(Array.from({ length: 15 }, (_, i) => graphicsKey([cam], 5.0 + i / fps, fps)))
  assert.ok(keys.size <= 2, `a still second of the camcorder makes ${keys.size} frames`)
})

test('the export draws only the seconds a graphic is on', () => {
  const g = { ...dressed('sparkles'), start: 2, end: 5, shown_end: 5 }
  const f = graphicFrames([g], 30, 10)
  assert.equal(f[0], 60)
  assert.equal(f[f.length - 1], 149)
  assert.equal(f.length, 90)
})
