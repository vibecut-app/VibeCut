// In a version laid out again for another frame, captions move off faces.
//
// Through the real drawOverlays onto a recording canvas (no pixels): a
// caption whose block covers a face slides to the nearest place that
// covers none, and its drawn words then miss the face and stay in the safe
// area; a face elsewhere, or on screen only before the caption, moves
// nothing; a face too big to miss gets the least-covering place; and the
// shift is applied for the caption's whole time on screen.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { drawOverlays, faceShifts, safe, type FaceArea, type OverlayBox } from './overlayDraw.ts'
import type { Overlay, OverlayStyle } from './types'

const W = 1080, H = 1920

// the Cozy look, as its record says (backend/looks/cozy.json)
const COZY = JSON.parse(readFileSync(join(import.meta.dirname, '../../backend/looks/cozy.json'), 'utf8'))
const style: OverlayStyle = {
  font: COZY.type.font, color: COZY.type.palette[0], accent: COZY.type.palette[1], captions: 'bottom', backing: COZY.type.backing,
  look: COZY.id, motion: { ...COZY.motion, case: COZY.type.case, track: COZY.type.track },
}
const cap = (id: string, start: number, end: number, text = 'the coffee here is unreal'): Overlay => ({
  id, kind: 'caption', text, sub: '', pos: 'bottom', size: 'M', anim: 'fade', dur: end - start,
  anchor: { to: 'edit' }, at: start, start, end, shown_end: end,
})

// a canvas that draws nothing and remembers each piece of text's box
function recorder() {
  let m = [1, 0, 0, 1, 0, 0]
  const stack: number[][] = []
  const boxes: { x: number; y: number; w: number; h: number }[] = []
  let px = 10
  const ctx = {
    font: '', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '', letterSpacing: '0px',
    shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    clearRect() {}, beginPath() {}, fill() {}, fillRect() {}, roundRect() {},
    save() { stack.push([...m]) }, restore() { m = stack.pop() ?? [1, 0, 0, 1, 0, 0] },
    translate(x: number, y: number) { m = [m[0], m[1], m[2], m[3], m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] },
    scale(a: number, b: number) { m = [m[0] * a, m[1] * a, m[2] * b, m[3] * b, m[4], m[5]] },
    rotate() {},
    measureText(t: string) {
      px = parseFloat(/(\d+(?:\.\d+)?)px/.exec(ctx.font)?.[1] ?? '10')
      return { width: t.length * px * 0.55 }
    },
    fillText(t: string, x: number, y: number) {
      const w = ctx.measureText(t).width
      const x0 = ctx.textAlign === 'center' ? x - w / 2 : ctx.textAlign === 'right' ? x - w : x
      boxes.push({ x: m[0] * x0 + m[4], y: m[3] * y + m[5], w: w * m[0], h: px * m[3] })
    },
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, boxes }
}

const hits = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h

/** Where the caption's block sits unmoved, mid-way through its time on screen. */
function blockOf(o: Overlay): OverlayBox {
  const { ctx } = recorder()
  const boxes: OverlayBox[] = []
  drawOverlays(ctx, W, H, [o], style, [], (o.start + o.shown_end) / 2, boxes)
  return boxes[0]
}

/** A face, in shares of the frame, right where `b` is. */
const faceOn = (b: OverlayBox, start: number, end: number): FaceArea =>
  ({ start, end, boxes: [[b.x / W, (b.y - 40) / H, Math.min(b.w, 300) / W, (b.h + 80) / H]] })

test('a caption over a face moves to the nearest clear place, and its words miss the face', () => {
  const o = cap('a', 1, 4)
  const b = blockOf(o)
  const face = faceOn(b, 0, 5)
  const { ctx } = recorder()
  const s = faceShifts(ctx, W, H, [o], style, [], [face])
  assert.ok(s.a, 'it moved')
  const [fx, fy, fw, fh] = face.boxes[0]
  const fr = { x: fx * W, y: fy * H, w: fw * W, h: fh * H }
  const sa = safe(W, H)
  for (const t of [1.2, 2.5, 3.9]) {
    const r = recorder()
    drawOverlays(r.ctx, W, H, [o], style, [], t, undefined, s)
    assert.ok(r.boxes.length, `drawn at ${t}`)
    for (const w of r.boxes) {
      assert.ok(!hits(w, fr), `at ${t}s the words (${w.y.toFixed(0)}) still sit on the face (${fr.y.toFixed(0)}–${(fr.y + fr.h).toFixed(0)})`)
      assert.ok(w.y >= sa.t - 2 && w.y + w.h <= H - sa.b + 2, 'still inside the safe area')
    }
  }
  // the nearest clear place: just past the face's edge (plus its margin), not across the frame
  const moved = s.a * H
  const need = moved < 0 ? b.y + b.h - fr.y : fr.y + fr.h - b.y
  assert.ok(Math.abs(moved) <= need + 0.02 * W + 0.01 * H + 2, `moved ${moved.toFixed(0)} px for ${need.toFixed(0)} px of overlap`)
})

test('a face elsewhere in the frame, or before the caption is on, moves nothing', () => {
  const o = cap('a', 3, 6)
  const b = blockOf(o)
  const { ctx } = recorder()
  const away: FaceArea = { start: 0, end: 10, boxes: [[0.4, 0.15, 0.2, 0.15]] }
  assert.deepEqual(faceShifts(ctx, W, H, [o], style, [], [away]), {})
  assert.deepEqual(faceShifts(ctx, W, H, [o], style, [], [faceOn(b, 0, 3)]), {}, 'the shot with the face ends as the caption starts')
  assert.ok(faceShifts(ctx, W, H, [o], style, [], [faceOn(b, 5.5, 8)]).a, 'a face on any part of its time counts')
  assert.deepEqual(faceShifts(ctx, W, H, [o], style, [], []), {})
})

test('a face too big to miss: the place that covers least, inside the safe area', () => {
  // from just under the safe area's top to below its bottom: only a sliver above is clear
  const o = cap('a', 0, 3)
  const big: FaceArea = { start: 0, end: 3, boxes: [[0, 0.13, 1, 0.8]] }
  const { ctx } = recorder()
  const s = faceShifts(ctx, W, H, [o], style, [], [big])
  assert.ok(s.a < 0, 'moved up, where the sliver is')
  const r = recorder()
  drawOverlays(r.ctx, W, H, [o], style, [], 1.5, undefined, s)
  const sa = safe(W, H)
  const top = Math.min(...r.boxes.map((w) => w.y))
  assert.ok(top >= sa.t - 2 && top <= sa.t + 0.02 * H, `as high as the safe area lets it (${top.toFixed(0)} vs ${sa.t.toFixed(0)})`)
})

test('each caption gets its own shift; one with no face keeps its place', () => {
  const a = cap('a', 0, 2), c = cap('c', 4, 6, 'and then the rain came')
  const { ctx } = recorder()
  const s = faceShifts(ctx, W, H, [a, c], style, [], [faceOn(blockOf(a), 0, 2)])
  assert.ok(s.a && !('c' in s), JSON.stringify(s))
})
