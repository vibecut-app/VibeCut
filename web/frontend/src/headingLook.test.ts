// Chapter titles (sarah, 2026-10-19): thin, white, widely spaced capitals
// with a small italic line under them in the same family, and a title that
// always fits the frame -- "MY WAY TO SCHOOL" ran off hers as "SCHOO".
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { drawOverlays, fitTitle, HEADING_DEFAULT, HEADINGS, motionFor, phase, pose, safe } from './overlayDraw.ts'
import type { Overlay, OverlayStyle } from './types'

const BASE: OverlayStyle = { font: 'Clean', color: '#ffffff', accent: '#b9d9eb', captions: 'bottom', backing: 'shadow' }
const heading = (text: string, sub = '', extra: Partial<Overlay> = {}): Overlay => ({
  id: 'h', kind: 'heading', text, sub, pos: 'center', size: 'M', anim: 'fade', dur: 2.4,
  anchor: { to: 'edit' }, at: 0, start: 0, end: 2.4, shown_end: 2.4, ...extra,
})

// a canvas that measures letters as 0.6 of their size plus the tracking, and
// records where each line lands and in what font
type Drawn = { text: string; font: string; fill: string; x0: number; x1: number; shadow: string }
function recorder() {
  let m = [1, 0, 0, 1, 0, 0]
  const stack: number[][] = []
  const drawn: Drawn[] = []
  const ctx = {
    font: '', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1,
    lineJoin: 'miter', letterSpacing: '0px', shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    clearRect() {}, beginPath() {}, fill() {}, fillRect() {}, roundRect() {}, strokeText() {},
    save() { stack.push([...m]) }, restore() { m = stack.pop() ?? [1, 0, 0, 1, 0, 0] },
    translate(x: number, y: number) { m = [m[0], m[1], m[2], m[3], m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] },
    scale(a: number, b: number) { m = [m[0] * a, m[1] * a, m[2] * b, m[3] * b, m[4], m[5]] },
    rotate() {},
    measureText(t: string) {
      const px = parseFloat(/(\d+(?:\.\d+)?)px/.exec(ctx.font)?.[1] ?? '10')
      return { width: t.length * (px * 0.6 + parseFloat(ctx.letterSpacing)) }
    },
    fillText(t: string, x: number, _y: number) {
      const ls = parseFloat(ctx.letterSpacing)
      const w = ctx.measureText(t).width
      const a = ctx.textAlign === 'center' ? x - w / 2 : ctx.textAlign === 'right' ? x - w : x
      drawn.push({ text: t, font: ctx.font, fill: String(ctx.fillStyle), x0: m[0] * a + m[4], x1: m[0] * (a + w - ls) + m[4],
        shadow: String(ctx.shadowColor) })
    },
  }
  return { ctx, drawn }
}
const draw = (o: Overlay, W = 1080, H = 1920) => {
  const r = recorder()
  drawOverlays(r.ctx as unknown as CanvasRenderingContext2D, W, H, [o], BASE, [], 1.2)
  return r.drawn
}

test('the default chapter title is thin, white, widely spaced capitals', () => {
  assert.equal(HEADING_DEFAULT, 'spaced')
  const t = HEADINGS.spaced
  assert.equal(t.color, '#ffffff')
  assert.ok(t.weight <= 300, `weight ${t.weight}`)
  assert.equal(t.case, 'upper')
  assert.ok((t.track ?? 0) >= 0.3, `tracking ${t.track}`)
  assert.equal(t.sub.family, t.family, 'the line under it is in the same family')
  assert.ok(t.italic, 'and italic')
})

test('a title and its line draw in that look: one line of capitals, an italic line under it', () => {
  const d = draw(heading('Coffee Run', 'finally coffee'))
  assert.equal(d.length, 2)
  assert.equal(d[0].text, 'COFFEE RUN')
  assert.match(d[0].font, /^300 \d+px "VC Montserrat"/)
  assert.equal(d[0].fill, '#ffffff')
  assert.match(d[1].font, /^italic 300 \d+px "VC Montserrat"/)
  assert.equal(d[1].text, 'finally coffee')
})

test('a heading with no look set wears the thin spaced one (older edits included)', () => {
  const d = draw(heading('Night In'))
  assert.match(d[0].font, /^300 /)
})

for (const [W, H] of [[1080, 1920], [1920, 1080]] as const) {
  test(`a long title always fits the frame on one line, every letter kept (${W}x${H})`, () => {
    const o = heading('My Way To School', '7:40 am · walk to class')
    const m = safe(W, H)
    const room = W - m.l - m.r
    const t = HEADINGS.spaced
    const full = Math.min(W, H) * t.size
    const unfitted = 'MY WAY TO SCHOOL'.length * (full * 0.6 + full * (t.track ?? 0))
    if (W < H) assert.ok(unfitted > room, 'the title would run off a vertical frame at its own size')
    const d = draw(o, W, H)
    const title = d.filter((x) => x.text === x.text.toUpperCase() && /[A-Z]/.test(x.text))
    assert.deepEqual(title.map((x) => x.text), ['MY WAY TO SCHOOL'], 'one line, nothing cut')
    assert.ok(title[0].x0 >= m.l - 0.5 && title[0].x1 <= W - m.r + 0.5,
      `title from ${title[0].x0.toFixed(0)} to ${title[0].x1.toFixed(0)}, room ${m.l.toFixed(0)}..${(W - m.r).toFixed(0)}`)
  })
}

test('a short title keeps its full size', () => {
  const W = 1080
  const d = draw(heading('OOTD'), W, 1920)
  const px = parseFloat(/(\d+)px/.exec(d[0].font)![1])
  assert.equal(px, Math.round(W * HEADINGS.spaced.size))
})

test('fitting shrinks only as much as it must, and never below its floor', () => {
  const measure = (s: string, px: number) => s.length * px * 0.6
  assert.equal(fitTitle(measure, 'OOTD', 40, 1000), 1)
  const k = fitTitle(measure, 'MY WAY TO SCHOOL', 40, 300)
  assert.ok(measure('MY WAY TO SCHOOL', 40 * k) <= 300 && measure('MY WAY TO SCHOOL', 40 * k / 0.94) > 300, `k ${k}`)
  assert.equal(fitTitle(measure, 'X'.repeat(200), 40, 10), 0.4)
})

test('a chapter title fades up and settles straight, whatever the look (no Cozy card tilt, no Hype slam)', () => {
  const o = heading('Coffee Run', 'finally coffee')
  for (const enter of ['card', 'slam'] as const) {
    const style: OverlayStyle = { ...BASE, motion: { curve: [0.2, 1, 0.3, 1], in_s: 1.15, step_fps: 12, stagger_s: 0.15, enter,
      case: 'lower', track: 0, beat_lock: false } }
    const m = motionFor(o, style)
    for (const t of [0.05, 0.2, 0.5, 1.2]) {
      const p = phase(o, t, m)
      const z = pose(o, p.pin, p.pout, 0, 1000, 'center', m)
      assert.equal(z.rot, 0, `${enter} at ${t}: tilted`)
      assert.equal(z.scale, 1, `${enter} at ${t}: scaled`)
    }
    const p = phase(o, 1.2, m)
    assert.equal(pose(o, p.pin, p.pout, 1, 1000, 'center', m).alpha, 1, 'fully in by 1.2 s, its line too')
  }
})

test('a title sized up by hand still fits the frame on one line, every letter kept', () => {
  const W = 1080, H = 1920
  const m = safe(W, H)
  const o = heading('My Way To School', '', { place: { x: 0.5, y: 0.5, scale: 3 } })
  const title = draw(o, W, H).filter((x) => /[A-Z]/.test(x.text))
  assert.deepEqual(title.map((x) => x.text), ['MY WAY TO SCHOOL'], 'one line, nothing cut')
  // placed by hand it may go to the frame's edge, never past it
  assert.ok(title[0].x0 >= 0 && title[0].x1 <= W && title[0].x1 - title[0].x0 <= W - m.l - m.r + 0.5,
    `title from ${title[0].x0.toFixed(0)} to ${title[0].x1.toFixed(0)}`)
})

test("where ink found nothing that reads, a title's halo wins over its soft shadow", () => {
  const plain = draw(heading('Coffee Run'))
  assert.equal(plain[0].shadow, 'rgba(0,0,0,0.5)', 'the soft shadow by default')
  const lit = draw(heading('Coffee Run', '', { halo: 'rgba(0,0,0,0.85)' }))
  assert.equal(lit[0].shadow, 'rgba(0,0,0,0.85)')
})
