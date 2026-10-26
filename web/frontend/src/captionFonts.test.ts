// Caption fonts: a picked font letters every caption line (and nothing that
// isn't a caption), each template keeps its own edge or backing around it,
// every font keeps a long caption inside the safe area, and every font in
// the picker ships with the app -- its files and licence in public/fonts,
// its id known to the backend -- so the export draws the same letters.
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { CAPTION_FONTS } from './captionFonts.ts'
import { drawOverlays, safe, TEMPLATES, typeLook } from './overlayDraw.ts'
import type { CaptionTemplate, Overlay, OverlayStyle } from './types'

const BASE: OverlayStyle = { font: 'Clean', color: '#ffffff', accent: '#b9d9eb', captions: 'bottom', backing: 'shadow' }
const ov = (kind: Overlay['kind'], text: string, sub = ''): Overlay => ({
  id: kind, kind, text, sub, pos: 'bottom', size: 'M', anim: 'fade', dur: 3,
  anchor: { to: 'edit' }, at: 0, start: 0, end: 3, shown_end: 3,
})

function draw(style: OverlayStyle, o: Overlay, W = 1080, H = 1920) {
  // a 2D context that records where each word lands, transforms included
  let m = [1, 0, 0, 1, 0, 0]
  const stack: number[][] = []
  const out: { text: string; font: string; stroked: boolean; pts: [number, number][] }[] = []
  let stroked = new Set<string>()
  const pxOf = () => parseFloat(/(\d+(?:\.\d+)?)px/.exec(ctx.font)?.[1] ?? '10')
  const ctx = {
    font: '', textAlign: 'left', textBaseline: 'top', globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1,
    lineJoin: 'miter', letterSpacing: '0px', shadowColor: '', shadowBlur: 0, shadowOffsetY: 0,
    clearRect() {}, beginPath() {}, fill() {}, fillRect() {}, roundRect() {},
    save() { stack.push([...m]) }, restore() { m = stack.pop() ?? [1, 0, 0, 1, 0, 0] },
    translate(x: number, y: number) { m = [m[0], m[1], m[2], m[3], m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] },
    scale(a: number, b: number) { m = [m[0] * a, m[1] * a, m[2] * b, m[3] * b, m[4], m[5]] },
    rotate(r: number) {
      const c = Math.cos(r), s = Math.sin(r)
      m = [m[0] * c + m[2] * s, m[1] * c + m[3] * s, -m[0] * s + m[2] * c, -m[1] * s + m[3] * c, m[4], m[5]]
    },
    measureText(t: string) { return { width: t.length * (pxOf() * 0.55 + parseFloat(ctx.letterSpacing)) } },
    strokeText(t: string) { stroked.add(t) },
    fillText(t: string, x: number, y: number) {
      const px = pxOf(), ls = parseFloat(ctx.letterSpacing), w = ctx.measureText(t).width
      const x0 = ctx.textAlign === 'center' ? x - w / 2 : ctx.textAlign === 'right' ? x - w : x
      const x1 = x0 + w - ls
      const pts: [number, number][] = [[x0, y], [x1, y], [x0, y + px], [x1, y + px]]
      out.push({ text: t, font: ctx.font, stroked: stroked.has(t),
                 pts: pts.map(([a, b]) => [m[0] * a + m[2] * b + m[4], m[1] * a + m[3] * b + m[5]]) })
      stroked = new Set()
    },
  }
  drawOverlays(ctx as unknown as CanvasRenderingContext2D, W, H, [o], style, [], 2)
  return out.filter((d) => d.text.trim())
}

test('a picked font letters every caption line, place name included', () => {
  for (const f of CAPTION_FONTS) {
    const lines = draw({ ...BASE, typeface: f.id }, ov('caption', 'coffee run', 'Shibuya'))
    assert.equal(lines.length, 2)
    for (const d of lines) assert.ok(d.font.includes(`"VC ${f.name}"`) && d.font.startsWith(`${f.weight} `), `${f.id}: ${d.font}`)
  }
  const own = draw(BASE, ov('caption', 'coffee run'))
  assert.ok(!own[0].font.includes('"VC '), 'no font picked: the style keeps its own')
})

test('the box a caption is typed into uses the picked font', () => {
  const look = typeLook(ov('caption', 'coffee run', 'Shibuya'), { ...BASE, template: 'outlined', typeface: 'pacifico' }, 400)
  assert.ok(look.main.font.includes('"VC Pacifico"') && look.lead!.font.includes('"VC Pacifico"'), look.main.font)
})

// the panel edits any words the video writes (a title, a stop's line), as
// CapCut's text panel does; a date stamp keeps its own lettering
test('captions and labels take the font, a date keeps its own', () => {
  assert.ok(draw({ ...BASE, typeface: 'anton' }, ov('title', 'Sep 22'))[0].font.includes('VC Anton'))
  assert.ok(!draw({ ...BASE, typeface: 'anton' }, ov('date', 'Sep 22'))[0].font.includes('VC Anton'))
})

test('a template keeps its edge around the picked font', () => {
  const lines = draw({ ...BASE, template: 'outlined', typeface: 'bebas-neue' }, ov('caption', 'lunch'))
  assert.ok(lines.every((d) => d.stroked && d.font.includes('VC Bebas Neue')))
})

for (const [W, H] of [[1080, 1920], [1920, 1080]]) {
  test(`every font with every template stays inside the ${W}x${H} safe area`, () => {
    const sa = safe(W, H), tol = 2
    const o = ov('caption', '7:42 am · we got completely lost and it was the best part of the trip', 'Shibuya')
    for (const tpl of [null, ...Object.keys(TEMPLATES)] as (CaptionTemplate | null)[]) for (const f of CAPTION_FONTS) {
      for (const d of draw({ ...BASE, template: tpl, typeface: f.id }, o, W, H)) for (const [x, y] of d.pts) {
        assert.ok(x >= sa.l - tol && x <= W - sa.r + tol && y >= sa.t - tol && y <= H - sa.b + tol,
          `${tpl} + ${f.id}: "${d.text}" at (${x.toFixed(0)}, ${y.toFixed(0)}) is outside the safe area`)
      }
    }
  })
}

test('every font ships with the app and the backend knows it', () => {
  const css = readFileSync(new URL('../public/fonts/fonts.css', import.meta.url), 'utf8')
  const py = readFileSync(new URL('../../backend/overlays.py', import.meta.url), 'utf8')
  for (const f of CAPTION_FONTS) {
    const faces = [...css.matchAll(/@font-face \{([^}]*)\}/g)].map((m) => m[1]).filter((b) => b.includes(`'VC ${f.name}'`))
    assert.ok(faces.length >= 1, `${f.name}: no @font-face`)
    for (const b of faces) {
      assert.ok(b.includes(`font-weight: ${f.weight};`), `${f.name}: weight ${f.weight} not shipped`)
      const file = /url\(\/fonts\/([^)]+)\)/.exec(b)![1]
      assert.ok(existsSync(new URL(`../public/fonts/${file}`, import.meta.url)), `${file} missing`)
    }
    assert.ok(existsSync(new URL(`../public/fonts/${f.id}/LICENSE`, import.meta.url)), `${f.id}: no licence`)
    assert.ok(py.includes(`"${f.id}": "${f.name}"`), `${f.id}: not in overlays.TYPEFACES`)
  }
})
