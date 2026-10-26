// The Captions tab's plain controls and word art. Each control has to move
// the drawing it names, and only that: an outline's width is the edge's
// width (0 = none, even on Outlined), a shadow is a shadow, a background is
// a box, boldness is a stroke in the letters' own colour. Captions with no
// template still take them. Each word art draws what it says: neon a
// coloured light, gradient a gradient, 3D its sides, retro one hard drop.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { dress, dressOf, drawOverlays, TEMPLATES, typeLook } from './overlayDraw.ts'
import type { Overlay, OverlayStyle } from './types'

const BASE: OverlayStyle = { font: 'Clean', color: '#ffffff', accent: '#b9d9eb', captions: 'bottom', backing: 'shadow' }
const cap: Overlay = { id: 'c', kind: 'caption', text: 'lunch', sub: '', pos: 'bottom', size: 'M', anim: 'fade', dur: 3,
  anchor: { to: 'edit' }, at: 0, start: 0, end: 3, shown_end: 3 }

type Call = { op: string; text?: string; x?: number; y?: number; lineWidth?: number; stroke?: string; fill?: unknown; shadow?: string; blur?: number }
function record(style: OverlayStyle) {
  const calls: Call[] = []
  const ctx = {
    font: '10px x', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '' as unknown, strokeStyle: '' as unknown, lineWidth: 1,
    lineJoin: 'miter', letterSpacing: '0px', shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    clearRect() {}, beginPath() {}, fill() { calls.push({ op: 'fill', fill: ctx.fillStyle }) }, fillRect() {},
    roundRect() { calls.push({ op: 'box' }) }, save() {}, restore() {}, translate() {}, scale() {}, rotate() {},
    createLinearGradient() { const g = { stops: [] as string[], addColorStop(_: number, c: string) { g.stops.push(c) } }; calls.push({ op: 'gradient' }); return g },
    measureText(t: string) { return { width: t.length * 10 } },
    strokeText(t: string, x: number, y: number) { calls.push({ op: 'stroke', text: t, x, y, lineWidth: ctx.lineWidth, stroke: String(ctx.strokeStyle) }) },
    fillText(t: string, x: number, y: number) { calls.push({ op: 'text', text: t, x, y, fill: ctx.fillStyle, shadow: ctx.shadowColor, blur: ctx.shadowBlur }) },
  }
  drawOverlays(ctx as unknown as CanvasRenderingContext2D, 1080, 1920, [cap], style, [], 2)
  return calls
}
const strokes = (c: Call[]) => c.filter((x) => x.op === 'stroke' && x.text === 'lunch')
const texts = (c: Call[]) => c.filter((x) => x.op === 'text' && x.text === 'lunch')

test('outline width is the edge width; 0 takes the edge away, even on Outlined', () => {
  const thin = strokes(record({ ...BASE, outline: { color: '#ff0000', width: 0.05 } }))
  const thick = strokes(record({ ...BASE, outline: { color: '#ff0000', width: 0.3 } }))
  assert.equal(thin.length, 1)
  assert.equal(thin[0].stroke, '#ff0000')
  assert.ok(Math.abs(thick[0].lineWidth! / thin[0].lineWidth! - 6) < 0.01, 'six times the width')
  assert.equal(strokes(record({ ...BASE, template: 'outlined', outline: { color: '#000000', width: 0 } })).length, 0)
  assert.equal(strokes(record({ ...BASE, template: 'outlined' })).length, 1, 'untouched, Outlined keeps its own edge')
})

test('shadow, background and boldness each draw what they say', () => {
  const sh = texts(record({ ...BASE, shadow: { color: '#3366ff', opacity: 0.5, blur: 0.4, dist: 0.1 } }))
  assert.equal(sh[0].shadow, 'rgba(51,102,255,0.5)')
  const none = texts(record({ ...BASE, template: 'outlined', shadow: { color: '#000000', opacity: 0, blur: 0.4, dist: 0.1 } }))
  assert.equal(none[0].shadow, 'rgba(0,0,0,0)')
  const box = record({ ...BASE, backdrop: { color: '#000000', opacity: 0.6, round: 0.3 } })
  assert.ok(box.some((c) => c.op === 'box'))
  assert.ok(box.some((c) => c.op === 'fill' && c.fill === 'rgba(0,0,0,0.6)'))
  assert.ok(!record({ ...BASE, template: 'label', backdrop: { color: '#000000', opacity: 0, round: 0.3 } }).some((c) => c.op === 'box'),
    'opacity 0 takes Label\'s backing away')
  const bold = strokes(record({ ...BASE, text_color: '#ffd84d', thick: 0.1 }))
  assert.ok(bold.some((c) => c.stroke === '#ffd84d'), 'a stroke in the letters\' own colour')
})

test('nothing set by hand draws exactly as before', () => {
  assert.equal(strokes(record(BASE)).length, 0)
  assert.ok(!record(BASE).some((c) => c.op === 'box'))
})

test('word art draws what it says', () => {
  assert.ok(texts(record({ ...BASE, template: 'neon' })).some((c) => c.shadow === '#ff2fd0' && c.blur! > 0), 'neon light')
  assert.ok(record({ ...BASE, template: 'gradient' }).some((c) => c.op === 'gradient'), 'gradient fill')
  const sides = texts(record({ ...BASE, template: 'extrude' }))
  assert.ok(sides.length > 3 && sides.some((c) => c.fill === '#1a1a1a'), '3D sides behind the face')
  const drop = texts(record({ ...BASE, template: 'retro' }))
  assert.equal(drop.length, 2, 'one hard drop + the face')
  assert.ok(drop[0].x! > drop[1].x! && drop[0].y! > drop[1].y!, 'drop sits down and to the right')
})

test('the sliders start from what the template has', () => {
  const d = dressOf({ ...BASE, template: 'outlined' })
  assert.equal(d.outline.width, TEMPLATES.outlined.stroke!.w)
  assert.equal(dressOf(BASE).backdrop.opacity, 0)
  assert.equal(dressOf({ ...BASE, template: 'label' }).backdrop.opacity, 1)
  assert.equal(dress(TEMPLATES.outlined, { ...BASE, thick: 0.05 }).thick, 0.05)
})

test('the typing box shows the same outline, background and word art', () => {
  const ol = typeLook(cap, { ...BASE, outline: { color: '#ff0000', width: 0.2 } }, 400)
  assert.equal(ol.main.stroke?.color, '#ff0000')
  const bg = typeLook(cap, { ...BASE, backdrop: { color: '#000000', opacity: 0.5, round: 0.2 } }, 400)
  assert.equal(bg.main.band?.fill, 'rgba(0,0,0,0.5)')
  assert.ok(typeLook(cap, { ...BASE, template: 'neon' }, 400).main.shadow.includes('#ff2fd0'))
})

// A made video's stop lines are part labels, not captions (sarah, 2026-10-20:
// the colour, shadow and font did nothing on "Columbia University, morning").
// The panel's look has to reach them too, and leave them alone until it's set.
test('a stop line (part label) takes the colour, shadow, outline, font and word art too', () => {
  const part: Overlay = { ...cap, id: 'p', kind: 'part', text: 'columbia', pos: 'top', size: 'S' }
  const draw = (style: OverlayStyle) => {
    const calls: Call[] = []
    const ctx = {
      font: '10px x', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '' as unknown, strokeStyle: '' as unknown, lineWidth: 1,
      lineJoin: 'miter', letterSpacing: '0px', shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
      clearRect() {}, beginPath() {}, fill() { calls.push({ op: 'fill', fill: ctx.fillStyle }) }, fillRect() {},
      roundRect() { calls.push({ op: 'box' }) }, save() {}, restore() {}, translate() {}, scale() {}, rotate() {},
      createLinearGradient() { return { addColorStop() {} } },
      measureText(t: string) { return { width: t.length * 10 } },
      strokeText(t: string, x: number, y: number) { calls.push({ op: 'stroke', text: t, x, y, lineWidth: ctx.lineWidth, stroke: String(ctx.strokeStyle) }) },
      fillText(t: string, x: number, y: number) { calls.push({ op: 'text', text: t, x, y, fill: ctx.fillStyle, shadow: ctx.shadowColor, font: ctx.font } as Call) },
    }
    drawOverlays(ctx as unknown as CanvasRenderingContext2D, 1080, 1920, [part], style, [], 2)
    return calls.filter((c) => c.text?.toLowerCase() === 'columbia')
  }
  const plain = draw(BASE)
  assert.ok(plain.every((c) => c.op === 'text' && c.fill === '#ffffff'), 'untouched, it draws as the look has it')
  assert.ok(draw({ ...BASE, text_color: '#ff3366' }).some((c) => c.op === 'text' && c.fill === '#ff3366'), 'colour')
  assert.ok(draw({ ...BASE, outline: { color: '#00ff00', width: 0.1 } }).some((c) => c.op === 'stroke' && c.stroke === '#00ff00'), 'outline')
  assert.ok(draw({ ...BASE, shadow: { color: '#3366ff', opacity: 0.5, blur: 0.4, dist: 0.1 } }).some((c) => c.shadow === 'rgba(51,102,255,0.5)'), 'shadow')
  assert.ok(draw({ ...BASE, template: 'outlined' }).some((c) => c.op === 'stroke'), 'word art')
  const font = draw({ ...BASE, typeface: 'anton' }) as (Call & { font?: string })[]
  assert.ok(font.some((c) => c.font?.includes('VC Anton')), 'font')
})

// A title and the line under it are a group (sarah, 2026-10-20): each line
// takes its own colour, outline, size and nudge, the other line keeps its
// look, and the drawing says where each line is so it can be picked.
test('one line of a group tuned on its own; each line reported for picking', () => {
  const head: Overlay = { ...cap, id: 'h', kind: 'heading', text: 'heading in', sub: '8:35 am · heading to class', pos: 'center' }
  const draw = (o: Overlay) => {
    const calls: Call[] = []
    const ctx = {
      font: '10px x', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '' as unknown, strokeStyle: '' as unknown, lineWidth: 1,
      lineJoin: 'miter', letterSpacing: '0px', shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
      clearRect() {}, beginPath() {}, fill() {}, fillRect() {}, roundRect() { calls.push({ op: 'box' }) },
      save() {}, restore() {}, translate() {}, scale() {}, rotate() {}, createLinearGradient() { return { addColorStop() {} } },
      measureText(t: string) { return { width: t.length * 10 } },
      strokeText(t: string, x: number, y: number) { calls.push({ op: 'stroke', text: t, x, y, stroke: String(ctx.strokeStyle) }) },
      fillText(t: string, x: number, y: number) { calls.push({ op: 'text', text: t, x, y, fill: ctx.fillStyle }) },
    }
    const boxes: import('./overlayDraw.ts').OverlayBox[] = []
    drawOverlays(ctx as unknown as CanvasRenderingContext2D, 1080, 1920, [o], BASE, [], 2, boxes)
    const sub = calls.filter((c) => c.text?.toLowerCase().includes('8:35'))
    const main = calls.filter((c) => c.text?.toLowerCase().includes('heading in'))
    return { sub, main, rows: boxes[0]?.rows ?? [] }
  }
  const plain = draw(head)
  assert.deepEqual(plain.rows.map((r) => r.role), ['main', 'sub'], 'both lines can be picked')
  const tuned = draw({ ...head, lines: { sub: { text_color: '#ff3366', outline: { color: '#00ff00', width: 0.1 }, scale: 1.5, dx: 0.1 } } })
  assert.ok(tuned.sub.some((c) => c.op === 'text' && c.fill === '#ff3366'), 'the line under takes its colour')
  assert.ok(tuned.sub.some((c) => c.op === 'stroke' && c.stroke === '#00ff00'), 'and its outline')
  assert.deepEqual(tuned.main, plain.main.map((c) => ({ ...c, y: tuned.main[0].y })), 'the title keeps its look')
  assert.ok(tuned.rows[1].h > plain.rows[1].h * 1.3, 'bigger')
  assert.ok(tuned.rows[1].x > plain.rows[1].x + 50, 'nudged right by a tenth of the short side')
})
