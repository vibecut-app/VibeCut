// Graphic animations, drawn (backend graphics.py; sarah, 2026-10-19: "make
// it an extra tool on the right called graphic animations"). One function
// draws every piece at time t onto any canvas: the preview over the player,
// the tiles in the tab and the export frames all call it, so what the creator
// watches is what gets exported -- the same contract as overlayDraw.ts.
//
// Each piece is a pure function of the time into it: nothing accumulates,
// nothing reads the clock, so the export can render any frame in any order.
// Sizes come from the frame's short side and positions from the same safe
// area as the captions, so a 400 px preview and a 1080×1920 export match.
// Everything is drawn over the creator's own frames; nothing is generated.

import { safe } from './overlayDraw.ts'
import type { Graphic, GraphicPiece, StickerKind } from './types'

type Ctx = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D
export type GraphicBox = { id: string; x: number; y: number; w: number; h: number }

/** What each piece is called and what it does, in the tab's words. */
export const PIECES: Record<GraphicPiece, { name: string; line: string; life: number }> = {
  title: { name: 'Title card', line: 'Your video\'s name builds itself in, the day above it', life: 3.5 },
  chapter: { name: 'Chapter opener', line: 'A number and the part\'s name, opening a part', life: 3.2 },
  route: { name: 'Route map', line: 'A little map drawing the way between your stops', life: 4 },
  pin: { name: 'Place pin', line: 'A pin drops and names where you are', life: 3 },
  camcorder: { name: 'Camcorder', line: 'REC, the time it was filmed, the frame of an old camera', life: 4 },
  clock: { name: 'Clock', line: 'The hands spin to the time this was filmed', life: 3.5 },
  stickers: { name: 'Beat sticker', line: 'A sticker that bounces on the beat of your music', life: 3 },
  sparkles: { name: 'Sparkles', line: 'Little stars twinkling over a spot', life: 3 },
  circle: { name: 'Circle it', line: 'A marker circle draws itself around something', life: 3 },
  progress: { name: 'Progress bar', line: 'A thin bar along the top fills as the video plays', life: 4 },
}
export const PIECE_ORDER: GraphicPiece[] = ['title', 'chapter', 'route', 'pin', 'camcorder', 'clock', 'stickers', 'sparkles', 'circle', 'progress']
export const STICKER_NAMES: Record<StickerKind, string> = {
  heart: 'Heart', star: 'Star', smile: 'Smile', sun: 'Sun', flower: 'Flower', bolt: 'Bolt', note: 'Music', sparkle: 'Sparkle',
}
/** Which pieces carry words the creator can change in the tab. */
export const HAS_WORDS: Record<GraphicPiece, 'two' | 'one' | null> = {
  title: 'two', chapter: 'two', route: null, pin: 'one', camcorder: 'one', clock: 'one',
  stickers: null, sparkles: null, circle: 'one', progress: null,
}
/** Frame-wide pieces aren't picked or dragged on the picture, only on the timeline. */
export const FRAMEWIDE: GraphicPiece[] = ['camcorder', 'progress']

// ---- fonts: bundled, openly licensed (public/fonts, "VC " families) ---------

const SERIF = '"VC Playfair Display", Georgia, serif'
const SANS = '"VC Montserrat", "Helvetica Neue", sans-serif'
const HAND = '"VC Caveat", "Bradley Hand", cursive'
const MONO = '"VC Courier Prime", "Courier New", monospace'
// The captions' fonts.css has one heavy weight of each family. The graphics'
// thin spaced capitals, readouts and italic numbers need lighter ones, which
// are added here, so nothing changes for the captions.
const LATIN = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD'
const LATIN_EXT = 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF'
const LIGHT: [string, string, string, string][] = [
  ['VC Montserrat', '400', 'normal', 'montserrat/montserrat-latin*-400-normal'],
  ['VC Montserrat', '500', 'normal', 'montserrat/montserrat-latin*-500-normal'],
  ['VC Playfair Display', '400', 'italic', 'playfair-display/playfair-display-latin*-400-italic'],
]
let lightAdded = false
function addLight() {
  if (lightAdded || typeof FontFace === 'undefined') return
  lightAdded = true
  for (const [family, weight, style, file] of LIGHT) {
    for (const [ext, unicodeRange] of [['', LATIN], ['-ext', LATIN_EXT]]) {
      document.fonts.add(new FontFace(family, `url(/fonts/${file.replace('*', ext)}.woff2) format('woff2')`, { weight, style, unicodeRange, display: 'swap' }))
    }
  }
}
const FONTS = [`700 40px ${SERIF}`, `italic 400 40px ${SERIF}`, `400 40px ${SANS}`, `500 40px ${SANS}`, `700 40px ${HAND}`, `400 40px ${MONO}`]

export async function ensureGraphicFonts(): Promise<void> {
  if (typeof document === 'undefined' || !document.fonts) return
  addLight()
  await Promise.all(FONTS.map((f) => document.fonts.load(f).catch(() => [])))
}

// ---- timing -----------------------------------------------------------------

const clamp01 = (x: number) => Math.max(0, Math.min(1, x))
const lerp = (a: number, b: number, x: number) => a + (b - a) * x
const out3 = (x: number) => 1 - (1 - clamp01(x)) ** 3
const inOut3 = (x: number) => { x = clamp01(x); return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2 }
const in2 = (x: number) => clamp01(x) ** 2
/** overshoots a little and settles: things that pop */
const back = (x: number) => { x = clamp01(x); const c = 1.6; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2 }
/** falls and bounces twice: the pin */
const bounce = (x: number) => {
  x = clamp01(x)
  const n = 7.5625, d = 2.75
  if (x < 1 / d) return n * x * x
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375
  return n * (x -= 2.625 / d) * x + 0.984375
}
/** 0..1 through the window [a, a + d] seconds */
const win = (el: number, a: number, d: number) => clamp01((el - a) / Math.max(1e-6, d))

/** How a piece's life is spent: the intro and outro shrink on a short one so
 *  it never spends most of its time arriving. `k` scales the intro's clock. */
function life(g: Graphic, t: number, intro: number, outro: number) {
  const d = Math.max(0.01, g.shown_end - g.start)
  const k = Math.min(1, (d * 0.6) / Math.max(0.01, intro))
  const o = Math.min(outro, d * 0.2)
  const el = t - g.start
  return { el: el / k, raw: el, d, k, gone: o > 0 ? in2(1 - clamp01((d - el) / o)) : 0 }
}

/** A stable 0..1 number from a graphic's id: where its sparkles sit, how its circle wobbles. */
function seeded(id: string) {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) { h ^= id.charCodeAt(i); h = Math.imul(h, 16777619) }
  return () => { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 100000) / 100000 }
}

// ---- drawing helpers ----------------------------------------------------------

function track(ctx: Ctx, px: number) {
  if ('letterSpacing' in ctx) (ctx as { letterSpacing: string }).letterSpacing = `${px}px`
}
function soft(ctx: Ctx, u: number, a = 0.45, blur = 0.02, dy = 0.003) {
  ctx.shadowColor = `rgba(0,0,0,${a})`
  ctx.shadowBlur = blur * u
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = dy * u
}
function noShadow(ctx: Ctx) {
  ctx.shadowColor = 'rgba(0,0,0,0)'
  ctx.shadowBlur = 0
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = 0
}
function rgba(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}
function darkInk(hex: string) {
  const n = parseInt(hex.slice(1), 16)
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] < 0.4
}
/** Words that fit `maxW`: shrink first (to 60%), then wrap onto at most
 *  `lines`. `tr` is the tracking, as a share of the size, so spaced capitals
 *  are measured as they'll be drawn. */
function fit(ctx: Ctx, text: string, font: (px: number) => string, px: number, maxW: number, lines = 2, tr = 0): { rows: string[]; px: number } {
  const width = (s: string, q: number) => {
    ctx.font = font(q)
    track(ctx, q * tr)
    return ctx.measureText(s).width - q * tr
  }
  for (let k = 1; k >= 0.6; k -= 0.05) {
    if (width(text, px * k) <= maxW) { track(ctx, 0); return { rows: [text], px: px * k } }
  }
  const q = px * 0.8
  const words = text.split(/\s+/)
  const rows: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (cur && width(next, q) > maxW) { rows.push(cur); cur = w } else cur = next
  }
  if (cur) rows.push(cur)
  if (rows.length > lines) { rows.length = lines; rows[lines - 1] = rows[lines - 1].replace(/\s*\S?$/, '') + '…' }
  track(ctx, 0)
  return { rows, px: q }
}

/** Where a piece sits: dragged by hand (its centre), else its own spot. */
function spot(g: Graphic, W: number, H: number, fallback: { x: number; y: number }) {
  return g.place ? { x: g.place.x * W, y: g.place.y * H, placed: true } : { ...fallback, placed: false }
}
const scaleOf = (g: Graphic) => g.size ?? 1

// ---- the pieces -----------------------------------------------------------------

type Draw = (ctx: Ctx, W: number, H: number, g: Graphic, t: number) => GraphicBox | null

// Words over footage carry a shadow strong enough to read over pale stone and
// white sky, the way the captions do.
const wordShadow = (ctx: Ctx, u: number) => soft(ctx, u, 0.55, 0.022, 0.004)
/** Light or thin words: a tight dark edge first, so the strokes hold over
 *  pale stone, then the soft shadow over it. */
function edged(ctx: Ctx, u: number, draw: () => void) {
  soft(ctx, u, 0.75, 0.003, 0.001)
  draw()
  wordShadow(ctx, u)
  draw()
}
// Strokes under ~4 px at 1080 break up in TikTok's and Instagram's compression.
const HAIR = 0.0037

// Title card: the day in small spaced capitals between two hairlines that
// grow out from the middle, then the name in a serif, letter by letter, each
// rising into place. Leaves by lifting and fading.
const title: Draw = (ctx, W, H, g, t) => {
  const { el, gone } = life(g, t, 1.4, 0.6)
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const c = spot(g, W, H, { x: W / 2, y: H * 0.44 })
  // centred on the frame, but no wider than the safe area allows on either side
  const maxW = c.placed ? (W - m.l - m.r) * 0.92 : 2 * Math.min(c.x - m.l, W - m.r - c.x) * 0.96
  const big = fit(ctx, g.text || ' ', (px) => `700 ${px}px ${SERIF}`, 0.092 * u, maxW, 2)
  const subPx = 0.03 * u
  const gap = 0.022 * u
  const lineH = big.px * 1.12
  const blockH = (g.sub ? subPx + gap : 0) + lineH * big.rows.length
  const top = c.y - blockH / 2 - gone * 0.03 * u
  ctx.save()
  ctx.globalAlpha = 1 - gone
  ctx.fillStyle = g.tint
  ctx.strokeStyle = g.tint
  ctx.textBaseline = 'top'
  wordShadow(ctx, u)
  let widest = 0
  if (g.sub) {
    const p = out3(win(el, 0.55, 0.7))
    const tr = lerp(0.62, 0.34, p) * subPx
    ctx.font = `500 ${subPx}px ${SANS}`
    track(ctx, tr)
    const sub = g.sub.toUpperCase()
    const sw = ctx.measureText(sub).width - tr
    ctx.globalAlpha = (1 - gone) * p
    ctx.textAlign = 'left'
    edged(ctx, u, () => ctx.fillText(sub, c.x - sw / 2, top))
    track(ctx, 0)
    // hairlines growing out of the words to either side
    const hp = out3(win(el, 0.7, 0.7)) * (1 - gone)
    const len = Math.min(0.11 * u, maxW / 2 - sw / 2 - gap)
    if (len > 0 && hp > 0) {
      ctx.globalAlpha = 1 - gone
      ctx.lineWidth = Math.max(1, HAIR * u)
      const y = top + subPx * 0.5
      ctx.beginPath()
      ctx.moveTo(c.x - sw / 2 - gap, y); ctx.lineTo(c.x - sw / 2 - gap - len * hp, y)
      ctx.moveTo(c.x + sw / 2 + gap, y); ctx.lineTo(c.x + sw / 2 + gap + len * hp, y)
      ctx.stroke()
    }
    widest = sw + 2 * (gap + Math.max(0, len))
  }
  ctx.font = `700 ${big.px}px ${SERIF}`
  ctx.textAlign = 'left'
  const n = big.rows.reduce((s, r) => s + r.length, 0)
  const step = Math.min(0.05, 0.75 / Math.max(1, n))
  let k = 0
  big.rows.forEach((row, r) => {
    const rw = ctx.measureText(row).width
    widest = Math.max(widest, rw)
    const x0 = c.x - rw / 2
    const y = top + (g.sub ? subPx + gap : 0) + r * lineH
    for (let i = 0; i < row.length; i++, k++) {
      const p = out3(win(el, 0.12 + k * step, 0.55))
      if (p <= 0) continue
      ctx.globalAlpha = (1 - gone) * p
      ctx.fillText(row[i], x0 + ctx.measureText(row.slice(0, i)).width, y + (1 - p) * big.px * 0.32)
    }
  })
  ctx.restore()
  return { id: g.id, x: c.x - widest / 2, y: top, w: widest, h: blockH }
}

// Chapter opener: the part's number rises out of a mask in the title's
// serif, in italics; its name follows in thin, widely spaced capitals, each
// letter fading up into place, and a hairline draws under the name once it's
// written. All one colour, like a magazine's section opener. Leaves to the left.
const chapter: Draw = (ctx, W, H, g, t) => {
  const { el, gone } = life(g, t, 1.2, 0.45)
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const numPx = 0.11 * u
  const num = g.sub || ''
  const name = (g.text || ' ').toUpperCase()
  const nameFont = (px: number) => `500 ${px}px ${SANS}`
  const numFont = `italic 400 ${numPx}px ${SERIF}`
  ctx.save()
  const nm = fit(ctx, name, nameFont, 0.032 * u, (W - m.l - m.r) * 0.8, 2, 0.3)
  const tr = nm.px * 0.3
  ctx.font = nameFont(nm.px)
  track(ctx, tr)
  const nameW = Math.max(...nm.rows.map((r) => ctx.measureText(r).width - tr))
  track(ctx, 0)
  ctx.font = numFont
  const numW = num ? ctx.measureText(num).width : 0
  const numH = num ? numPx * 1.08 : 0
  const gap = num ? 0.006 * u : 0
  const rowH = nm.px * 1.6
  const ruleGap = 0.018 * u, ruleH = Math.max(1.5, HAIR * u)
  const blockW = Math.max(numW + numPx * 0.12, nameW)   // italics lean out a little
  const blockH = numH + gap + (nm.rows.length - 1) * rowH + nm.px + ruleGap + ruleH
  const c = spot(g, W, H, { x: m.l + blockW / 2, y: H * 0.42 })
  const left = c.x - blockW / 2 - gone * 0.05 * u
  const top = c.y - blockH / 2
  // a soft shade behind the block: nothing on dark footage, something for
  // light words to sit on over pale stone (the export can't see the pixels
  // behind, so it's built in); kept inside the frame
  const sx = left + blockW * 0.45, sy = top + blockH * 0.55
  const rx = Math.min(0.75 * blockW, sx, W - sx), ry = Math.min(0.9 * blockH, sy, H - sy)
  if (rx > 0 && ry > 0) {
    ctx.save()
    ctx.globalAlpha = out3(win(el, 0, 0.4)) * (1 - gone)
    ctx.translate(sx, sy)
    ctx.scale(1, ry / rx)
    const shade = ctx.createRadialGradient(0, 0, 0, 0, 0, rx)
    shade.addColorStop(0, 'rgba(0,0,0,0.26)')
    shade.addColorStop(0.6, 'rgba(0,0,0,0.12)')
    shade.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = shade
    ctx.beginPath()
    ctx.arc(0, 0, rx, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }
  ctx.fillStyle = g.tint
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  wordShadow(ctx, u)
  // the number, up out of its mask
  if (num) {
    const np = out3(win(el, 0.05, 0.6))
    ctx.save()
    ctx.globalAlpha = 1 - gone
    ctx.beginPath()
    ctx.rect(left - numPx * 0.1, top - numPx * 0.12, numW + numPx * 0.4, numH + numPx * 0.18)
    ctx.clip()
    ctx.font = numFont
    edged(ctx, u, () => ctx.fillText(num, left, top + (1 - np) * numH))
    ctx.restore()
  }
  // the name, each letter fading up into place
  const ny = top + numH + gap
  ctx.font = nameFont(nm.px)
  track(ctx, tr)
  const total = nm.rows.reduce((s, r) => s + r.length, 0)
  const per = Math.min(0.03, 0.5 / Math.max(1, total))
  const from = num ? 0.35 : 0.1
  let k = 0
  nm.rows.forEach((row, r) => {
    for (let i = 0; i < row.length; i++, k++) {
      const p = out3(win(el, from + k * per, 0.25))
      if (p <= 0 || row[i] === ' ') continue
      ctx.globalAlpha = (1 - gone) * p
      const x = left + ctx.measureText(row.slice(0, i)).width, y = ny + r * rowH + (1 - p) * nm.px * 0.45
      edged(ctx, u, () => ctx.fillText(row[i], x, y))
    }
  })
  track(ctx, 0)
  // a hairline under the name, once it's written
  const rp = out3(win(el, from + total * per, 0.4))
  if (rp > 0) {
    ctx.globalAlpha = 1 - gone
    ctx.fillRect(left, ny + (nm.rows.length - 1) * rowH + nm.px + ruleGap, nameW * rp, ruleH)
  }
  ctx.restore()
  return { id: g.id, x: left, y: top, w: blockW, h: blockH }
}

/** A map pin's outline, its point at (0, 0), `ph` tall and `R` round. */
function teardrop(ctx: Ctx, ph: number, R: number) {
  ctx.beginPath()
  ctx.moveTo(0, 0)
  ctx.bezierCurveTo(-R * 0.35, -ph * 0.32, -R, -ph * 0.48, -R, -ph + R)
  ctx.arc(0, -ph + R, R, Math.PI, 0)
  ctx.bezierCurveTo(R, -ph * 0.48, R * 0.35, -ph * 0.32, 0, 0)
  ctx.closePath()
}

/** A gentle curve through every point (Catmull-Rom), `k` samples a span, so
 *  a line can draw itself along it. Point i of `ps` is sample i·k. */
function curveThrough(ps: { x: number; y: number }[], k: number) {
  const out = [ps[0]]
  for (let i = 0; i < ps.length - 1; i++) {
    const p0 = ps[Math.max(0, i - 1)], p1 = ps[i], p2 = ps[i + 1], p3 = ps[Math.min(ps.length - 1, i + 2)]
    for (let j = 1; j <= k; j++) {
      const s = j / k, s2 = s * s, s3 = s2 * s
      const at = (a: number, b: number, c: number, d: number) =>
        0.5 * (2 * b + (-a + c) * s + (2 * a - 5 * b + 4 * c - d) * s2 + (-a + 3 * b - 3 * c + d) * s3)
      out.push({ x: at(p0.x, p1.x, p2.x, p3.x), y: at(p0.y, p1.y, p2.y, p3.y) })
    }
  }
  return out
}

// Route map: a paper card with a few faint streets and the day's stops; the
// way already travelled draws itself in the piece's colour along a gentle
// curve to the stop you're at, where a little pin drops, and the way still to
// come waits as grey dots. Where you started and where you are are named.
const route: Draw = (ctx, W, H, g, t) => {
  const { el, gone, raw, k: pace } = life(g, t, 1.6, 0.4)
  const stops = g.stops ?? []
  if (stops.length < 2) return null
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const aspect = Math.max(0.6, Math.min(1.8, g.aspect ?? 1))
  const cw = 0.44 * u * (aspect >= 1 ? 1 : 0.85)
  const ch = cw / aspect
  const pad = 0.13 * Math.min(cw, ch) + 0.02 * u
  const labelH = 0.07 * u
  const cardH = ch + labelH
  const c = spot(g, W, H, { x: m.l + cw / 2, y: m.t + cardH / 2 })
  const pin = out3(win(el, 0, 0.4))
  const s = lerp(0.88, 1, back(win(el, 0, 0.45))) * (1 - gone * 0.08)
  const rnd = seeded(g.id)
  ctx.save()
  ctx.globalAlpha = pin * (1 - gone)
  ctx.translate(c.x, c.y)
  ctx.scale(s, s)
  ctx.translate(-cw / 2, -cardH / 2)
  // the card
  soft(ctx, u, 0.28, 0.035, 0.008)
  ctx.fillStyle = 'rgba(255,251,244,0.96)'
  ctx.beginPath()
  ctx.roundRect(0, 0, cw, cardH, 0.06 * cw)
  ctx.fill()
  noShadow(ctx)
  // map paper: two streets across and one down, the same for this piece every
  // time, and a fold between the map and its words
  ctx.strokeStyle = 'rgba(60,50,40,0.07)'
  ctx.lineWidth = 0.01 * u
  ctx.beginPath()
  for (let i = 0; i < 2; i++) { ctx.moveTo(0, (0.18 + 0.64 * rnd()) * ch); ctx.lineTo(cw, (0.18 + 0.64 * rnd()) * ch) }
  const sx = (0.25 + 0.5 * rnd()) * cw
  ctx.moveTo(sx, 0); ctx.lineTo(Math.max(0.1 * cw, Math.min(0.9 * cw, sx + (rnd() - 0.5) * 0.3 * cw)), ch)
  ctx.stroke()
  ctx.strokeStyle = 'rgba(60,50,40,0.1)'
  ctx.lineWidth = Math.max(1, 0.0025 * u)
  ctx.beginPath(); ctx.moveTo(0, ch); ctx.lineTo(cw, ch); ctx.stroke()
  const P = stops.map((p) => ({ x: pad + p.x * (cw - 2 * pad), y: pad + p.y * (ch - 2 * pad) }))
  const here = Math.max(0, Math.min(stops.length - 1, g.here ?? 0))
  const K = 24
  const lo = pad * 0.4
  const way = curveThrough(P, K).map((p) => ({ x: Math.max(lo, Math.min(cw - lo, p.x)), y: Math.max(lo, Math.min(ch - lo, p.y)) }))
  const along = [0]
  for (let i = 1; i < way.length; i++) along.push(along[i - 1] + Math.hypot(way[i].x - way[i - 1].x, way[i].y - way[i - 1].y))
  // the way still to come, as dots
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.lineWidth = Math.max(1.5, 0.008 * u)
  ctx.strokeStyle = 'rgba(60,50,40,0.3)'
  ctx.setLineDash([ctx.lineWidth * 0.1, ctx.lineWidth * 2.2])
  ctx.beginPath()
  way.slice(here * K).forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)))
  ctx.stroke()
  ctx.setLineDash([])
  // the way travelled, drawing itself in
  const travel = inOut3(win(el, 0.35, 1.1))
  const drawn = along[here * K] * travel
  ctx.strokeStyle = g.tint
  ctx.lineWidth = Math.max(2, 0.011 * u)
  ctx.beginPath()
  ctx.moveTo(way[0].x, way[0].y)
  let head = way[0]
  for (let i = 1; i <= here * K && along[i - 1] < drawn; i++) {
    const f = Math.min(1, (drawn - along[i - 1]) / Math.max(1e-6, along[i] - along[i - 1]))
    head = { x: lerp(way[i - 1].x, way[i].x, f), y: lerp(way[i - 1].y, way[i].y, f) }
    ctx.lineTo(head.x, head.y)
  }
  if (here > 0) ctx.stroke()
  // the stops passed and still to come
  const r = Math.max(2.5, 0.014 * u)
  P.forEach((p, i) => {
    if (i === here) return
    const on = i < here && along[i * K] <= drawn + 1e-6
    ctx.beginPath()
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
    ctx.fillStyle = on ? g.tint : '#ffffff'
    ctx.fill()
    ctx.lineWidth = Math.max(1, HAIR * u)
    ctx.strokeStyle = on ? '#ffffff' : 'rgba(60,50,40,0.45)'
    ctx.stroke()
  })
  // you are here: once the line arrives a small pin drops on the stop and a
  // ring keeps going out from under it; until then a dot leads the line
  const arrived = raw - 1.45 * pace
  const at = P[here]
  if (arrived > 0 || here === 0) {
    const since = here === 0 ? raw - 0.35 * pace : arrived
    const pop = back(clamp01(since / 0.35))
    const ring = (since % 1.4) / 1.4
    if (since > 0.25) {
      ctx.beginPath()
      ctx.ellipse(at.x, at.y, r * (0.6 + 1.6 * out3(ring)), r * (0.25 + 0.6 * out3(ring)), 0, 0, Math.PI * 2)
      ctx.strokeStyle = rgba(g.tint, 0.6 * (1 - ring))
      ctx.lineWidth = Math.max(1.5, HAIR * u)
      ctx.stroke()
    }
    if (pop > 0) {
      ctx.save()
      ctx.translate(at.x, at.y)
      ctx.scale(pop, pop)
      soft(ctx, u, 0.3, 0.012, 0.003)
      const ph = 0.04 * u, R = 0.0145 * u
      teardrop(ctx, ph, R)
      ctx.fillStyle = g.tint
      ctx.fill()
      noShadow(ctx)
      ctx.beginPath()
      ctx.arc(0, -ph + R, R * 0.42, 0, Math.PI * 2)
      ctx.fillStyle = '#ffffff'
      ctx.fill()
      ctx.restore()
    }
  } else if (travel > 0) {
    ctx.beginPath()
    ctx.arc(head.x, head.y, r * 0.9, 0, Math.PI * 2)
    ctx.fillStyle = g.tint
    ctx.fill()
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = Math.max(1, HAIR * u)
    ctx.stroke()
  }
  // where you started, small and grey beside its stop, away from the way out
  const first = here > 0 ? stops[0].name : null
  if (first) {
    ctx.globalAlpha = pin * (1 - gone) * out3(win(el, 0.5, 0.4))
    const fl = fit(ctx, first, (px) => `500 ${px}px ${SANS}`, 0.024 * u, cw * 0.5, 1)
    ctx.font = `500 ${fl.px}px ${SANS}`
    ctx.fillStyle = 'rgba(60,50,40,0.62)'
    ctx.textAlign = 'left'
    const fw = ctx.measureText(fl.rows[0]).width
    const below = way[Math.min(way.length - 1, 4)].y < P[0].y
    ctx.textBaseline = below ? 'top' : 'bottom'
    const fx = Math.max(lo, Math.min(cw - lo - fw, P[0].x - fw / 2))
    ctx.fillText(fl.rows[0], fx, below ? P[0].y + r * 1.6 : P[0].y - r * 1.6)
  }
  // where you are, in words, along the bottom of the card
  const name = stops[here]?.name
  if (name) {
    const lp = out3(win(el, 1.1, 0.5))
    ctx.globalAlpha = pin * (1 - gone) * lp
    const lab = fit(ctx, name, (px) => `500 ${px}px ${SANS}`, 0.034 * u, cw - 2 * pad * 0.7 - 0.034 * u, 1)
    const ly = ch + labelH / 2
    ctx.beginPath()
    ctx.arc(pad * 0.7 + lab.px * 0.3, ly, lab.px * 0.26, 0, Math.PI * 2)
    ctx.fillStyle = g.tint
    ctx.fill()
    ctx.font = `500 ${lab.px}px ${SANS}`
    ctx.fillStyle = '#2a2420'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(lab.rows[0], pad * 0.7 + lab.px * 0.9, ly + (1 - lp) * lab.px * 0.3)
  }
  ctx.restore()
  return { id: g.id, x: c.x - (cw * s) / 2, y: c.y - (cardH * s) / 2, w: cw * s, h: cardH * s }
}

// Place pin: a map pin drops and bounces, squashing where it lands, a ring
// spreads on the ground, and the place's name slides out of it on a white tab.
const pin: Draw = (ctx, W, H, g, t) => {
  const { el, gone } = life(g, t, 1.1, 0.4)
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const ph = 0.075 * u, pw = 0.055 * u
  const labPx = 0.034 * u
  ctx.save()
  const lab = fit(ctx, g.text || ' ', (px) => `500 ${px}px ${SANS}`, labPx, (W - m.l - m.r) * 0.7 - pw, 1)
  ctx.font = `500 ${lab.px}px ${SANS}`
  const tw = ctx.measureText(lab.rows[0]).width
  const tabH = lab.px * 1.9, tabW = tw + lab.px * 1.6
  const blockW = pw + 0.012 * u + tabW, blockH = ph + 0.012 * u
  const c = spot(g, W, H, { x: m.l + blockW / 2, y: m.t + 0.06 * H + blockH / 2 })
  const px = c.x - blockW / 2 + pw / 2          // the pin's tip
  const ground = c.y + blockH / 2 - 0.006 * u
  const drop = bounce(win(el, 0, 0.7))
  // flattened for a moment each time it touches the ground (bounce()'s contacts)
  const squash = 1 - 0.14 * Math.exp(-(((el - 0.255) / 0.04) ** 2)) - 0.06 * Math.exp(-(((el - 0.509) / 0.03) ** 2))
  const fall = (1 - drop) * 0.22 * u
  const popOut = 1 - gone
  ctx.globalAlpha = clamp01(el * 6) * (1 - gone)
  // the shadow it lands on, and the ring where it lands
  ctx.fillStyle = `rgba(0,0,0,${0.28 * drop})`
  ctx.beginPath()
  ctx.ellipse(px, ground, pw * 0.38 * (0.5 + 0.5 * drop), pw * 0.11, 0, 0, Math.PI * 2)
  ctx.fill()
  const rp = win(el, 0.3, 0.7)
  if (rp > 0 && rp < 1) {
    ctx.strokeStyle = rgba(g.tint, 0.7 * (1 - rp))
    ctx.lineWidth = Math.max(1.5, 0.005 * u)
    ctx.beginPath()
    ctx.ellipse(px, ground, pw * (0.4 + 1.1 * out3(rp)), pw * (0.12 + 0.33 * out3(rp)), 0, 0, Math.PI * 2)
    ctx.stroke()
  }
  // the pin: a teardrop, its point on the ground
  ctx.save()
  ctx.translate(px, ground - fall)
  ctx.scale(popOut * (2 - squash), popOut * squash)
  soft(ctx, u, 0.3, 0.015, 0.004)
  const R = pw / 2
  teardrop(ctx, ph, R)
  ctx.fillStyle = g.tint
  ctx.fill()
  noShadow(ctx)
  ctx.beginPath()
  ctx.arc(0, -ph + R, R * 0.42, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.restore()
  // the name on a tab sliding out of the pin
  const tp = out3(win(el, 0.55, 0.45)) * (1 - gone)
  if (tp > 0) {
    const tx = px + pw / 2 + 0.012 * u
    const ty = ground - ph + R - tabH / 2
    ctx.save()
    ctx.beginPath()
    ctx.rect(tx, ty - 4, tabW * tp + 2, tabH + 8)
    ctx.clip()
    soft(ctx, u, 0.25, 0.02, 0.004)
    ctx.fillStyle = 'rgba(255,255,255,0.96)'
    ctx.beginPath()
    ctx.roundRect(tx, ty, tabW, tabH, tabH / 2)
    ctx.fill()
    noShadow(ctx)
    ctx.fillStyle = '#1f1b1a'
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'
    ctx.fillText(lab.rows[0], tx + lab.px * 0.8, ty + tabH / 2 + lab.px * 0.04)
    ctx.restore()
  }
  ctx.restore()
  return { id: g.id, x: c.x - blockW / 2, y: ground - ph, w: blockW, h: ph + 0.01 * u }
}

// Camcorder: the frame of an old video camera over the whole picture --
// corner marks, a blinking REC, a battery, and the time the moment was
// filmed ticking in the bottom-left corner (as filmed, shot by shot; with no
// recording time, the video's own running time). Switches on with a flicker.
const camcorder: Draw = (ctx, W, H, g, t) => {
  const { raw: el, gone } = life(g, t, 0.3, 0.25)
  const u = Math.min(W, H)
  const m = safe(W, H)
  const flick = el < 0.08 ? 1 : el < 0.14 ? 0.25 : el < 0.2 ? 0.85 : 1
  const a = flick * (1 - gone)
  if (a <= 0) return null
  const inset = Math.min(m.l, m.r) * 0.75
  // on a vertical video the bottom corners hug the safe area (the app's
  // buttons and words are below it), so the readout sits in its corner
  const L = inset, R = W - inset, T = m.t * 0.7, B = H > W ? H - m.b + 0.035 * u : H - m.b * 0.62
  const arm = 0.065 * u, lw = Math.max(2, 0.0055 * u)
  const tint = g.tint
  ctx.save()
  ctx.globalAlpha = a
  ctx.strokeStyle = tint
  ctx.fillStyle = tint
  ctx.lineWidth = lw
  ctx.lineCap = 'square'
  soft(ctx, u, 0.6, 0.012, 0.002)
  ctx.beginPath()
  for (const [x, y, dx, dy] of [[L, T, 1, 1], [R, T, -1, 1], [L, B, 1, -1], [R, B, -1, -1]]) {
    ctx.moveTo(x, y + dy * arm); ctx.lineTo(x, y); ctx.lineTo(x + dx * arm, y)
  }
  ctx.stroke()
  const px = 0.036 * u
  ctx.font = `400 ${px}px ${MONO}`
  ctx.textBaseline = 'top'
  // REC, its dot blinking once a second; the words inside the corners but
  // never under an app's buttons (the safe area), the marks to the frame's edge
  const pad = 0.028 * u
  const tl = { x: Math.max(L + pad, m.l), y: Math.max(T + pad, m.t) }
  const bl = { x: tl.x, y: H > W ? B - arm - 0.01 * u : Math.min(B - pad, H - m.b) }
  const on = el % 1 < 0.62
  if (on) {
    ctx.beginPath()
    ctx.arc(tl.x + px * 0.32, tl.y + px * 0.5, px * 0.32, 0, Math.PI * 2)
    ctx.fillStyle = '#ff3b30'
    ctx.fill()
  }
  ctx.fillStyle = tint
  ctx.lineWidth = px * 0.06
  ctx.lineJoin = 'round'
  const word = (s: string, x: number, y: number) => {
    ctx.textAlign = 'left'
    ctx.strokeText(s, x, y)   // a hair heavier than the face, as a camera's display reads
    ctx.fillText(s, x, y)
  }
  word('REC', tl.x + px * 0.85, tl.y)
  // a battery, three bars, as far inside its corner as REC is inside its own
  const bw = px * 1.5, bh = px * 0.75, nub = px * 0.14
  const bx = R - (tl.x - L) - bw - nub, by = tl.y + px * 0.12
  ctx.lineWidth = Math.max(1.5, px * 0.08)
  ctx.strokeRect(bx, by, bw, bh)
  ctx.fillRect(bx + bw, by + bh * 0.3, nub, bh * 0.4)
  for (let i = 0; i < 3; i++) ctx.fillRect(bx + px * 0.14 + i * (bw - px * 0.28) / 3, by + px * 0.12, (bw - px * 0.28) / 3 - px * 0.08, bh - px * 0.24)
  // the time as filmed, else the running time, and the date under it
  ctx.lineWidth = px * 0.06
  const sec = filmedAt(g, t)
  const clock = sec == null ? running(t - g.start) : ampm(sec)
  word(clock, bl.x, bl.y - px * (g.text ? 2.25 : 1.05))
  if (g.text) word(g.text.toUpperCase(), bl.x, bl.y - px * 1.05)
  ctx.restore()
  return null
}
function filmedAt(g: Graphic, t: number): number | null {
  for (const [a, z, s, sp] of g.times ?? []) if (t >= a && t < z) return s + (t - a) * sp
  return null
}
const two = (n: number) => String(Math.floor(n)).padStart(2, '0')
function ampm(sec: number) {
  const s = ((sec % 86400) + 86400) % 86400
  const h = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = Math.floor(s) % 60
  return `${h < 12 ? 'AM' : 'PM'} ${(h % 12) || 12}:${two(mm)}:${two(ss)}`
}
const running = (s: number) => `${two(s / 3600)}:${two((s / 60) % 60)}:${two(s % 60)}`

// Clock: a white face pops in and its hands spin forward to the time this
// moment was filmed, the time counting up under it with them; then a thin
// second hand fades on at the second it was filmed and ticks. With no
// recording time under it the hands settle at ten past ten and no time is
// written, rather than a made-up one.
const clock: Draw = (ctx, W, H, g, t) => {
  const { el, raw, gone } = life(g, t, 1.4, 0.35)
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const R = 0.085 * u
  const readPx = 0.036 * u
  const known = g.clock != null
  const readFont = `500 ${readPx}px ${SANS}`
  // its words under it, shrunk to fit the frame's width; the block moves in
  // from the edge far enough for the widest of face, time and words
  const lab = g.text ? fit(ctx, g.text, (px) => `700 ${px}px ${HAND}`, 0.05 * u, W - m.l - m.r, 1) : null
  const labPx = lab?.px ?? 0
  ctx.font = `700 ${labPx}px ${HAND}`
  const labW = lab ? ctx.measureText(lab.rows[0]).width : 0
  ctx.font = readFont
  const readW = known ? ctx.measureText('12:59 pm').width : 0
  const half = Math.max(R, labW / 2, readW / 2)
  const readH = known ? readPx * 1.25 : 0
  const blockH = 2 * R + 0.02 * u + readH + (lab ? labPx * 1.1 : 0)
  const c = spot(g, W, H, { x: W - m.r - half - 0.01 * u, y: m.t + blockH / 2 })
  const cy = c.y - blockH / 2 + R
  const s = back(win(el, 0, 0.45)) * (1 - gone * 0.3)
  const target = known ? (g.clock as number) : 10 * 60 + 10
  const from = Math.max(0, target - 120)
  const now = lerp(from, target, inOut3(win(el, 0.25, 1.05)))
  ctx.save()
  ctx.globalAlpha = clamp01(el * 5) * (1 - gone)
  ctx.translate(c.x, cy)
  ctx.scale(s, s)
  soft(ctx, u, 0.3, 0.03, 0.006)
  ctx.beginPath()
  ctx.arc(0, 0, R, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(255,255,255,0.97)'
  ctx.fill()
  noShadow(ctx)
  // a rim, so the face holds its edge against a white sky
  ctx.lineWidth = R * 0.035
  ctx.strokeStyle = 'rgba(0,0,0,0.14)'
  ctx.stroke()
  ctx.strokeStyle = '#2a2a2e'
  ctx.lineCap = 'round'
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2, big = i % 3 === 0
    ctx.lineWidth = Math.max(1, R * (big ? 0.045 : 0.025))
    ctx.beginPath()
    ctx.moveTo(Math.sin(a) * R * (big ? 0.72 : 0.78), -Math.cos(a) * R * (big ? 0.72 : 0.78))
    ctx.lineTo(Math.sin(a) * R * 0.86, -Math.cos(a) * R * 0.86)
    ctx.stroke()
  }
  const hand = (turns: number, len: number, w: number, color: string) => {
    const a = turns * Math.PI * 2
    ctx.strokeStyle = color
    ctx.lineWidth = Math.max(1, w)
    ctx.beginPath()
    ctx.moveTo(-Math.sin(a) * R * 0.12, Math.cos(a) * R * 0.12)
    ctx.lineTo(Math.sin(a) * len, -Math.cos(a) * len)
    ctx.stroke()
  }
  hand((((now % 720) + 720) % 720) / 720, R * 0.5, R * 0.075, '#1d1d1f')
  hand((((now % 60) + 60) % 60) / 60, R * 0.74, R * 0.05, '#1d1d1f')
  const sp = out3(win(raw, 1.3, 0.3))
  if (known && sp > 0) {
    const sec0 = Math.round(((target % 1) + 1) % 1 * 60)
    ctx.globalAlpha *= sp
    hand((sec0 + Math.floor(Math.max(0, raw - 1.3))) / 60, R * 0.8, R * 0.025, g.tint)
    ctx.globalAlpha = clamp01(el * 5) * (1 - gone)
  }
  ctx.beginPath()
  ctx.arc(0, 0, R * 0.07, 0, Math.PI * 2)
  ctx.fillStyle = g.tint
  ctx.fill()
  ctx.restore()
  // the time, counting up with the hands, and its words under it
  ctx.save()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillStyle = '#ffffff'
  if (known) {
    ctx.globalAlpha = out3(win(el, 0.2, 0.4)) * (1 - gone)
    ctx.font = readFont
    const h = Math.floor(now / 60) % 24, mi = Math.floor(now % 60)
    edged(ctx, u, () => ctx.fillText(`${(h % 12) || 12}:${two(mi)} ${h < 12 ? 'am' : 'pm'}`, c.x, cy + R + 0.02 * u))
  }
  if (lab) {
    ctx.globalAlpha = out3(win(el, 0.7, 0.35)) * (1 - gone)
    ctx.font = `700 ${labPx}px ${HAND}`
    edged(ctx, u, () => ctx.fillText(lab.rows[0], c.x, cy + R + 0.02 * u + readH))
  }
  ctx.restore()
  return { id: g.id, x: c.x - R, y: cy - R, w: 2 * R, h: blockH }
}

// Beat sticker: a die-cut sticker that pops on and hops on every beat of the
// music (or a steady 120 a minute with none), swinging a little left, then
// right. Each hop takes a moment to rise, so it reads as a bounce, not a jump cut.
const stickers: Draw = (ctx, W, H, g, t) => {
  const { el, raw, gone } = life(g, t, 0.4, 0.25)
  const u = Math.min(W, H) * scaleOf(g)
  const m = safe(W, H)
  const S = 0.16 * u
  const c = spot(g, W, H, { x: W - m.r - S * 0.8, y: m.t + H * 0.16 })
  const bpm = g.beat?.bpm ?? 120
  const period = 60 / bpm
  const phase = g.beat ? g.beat.phase : g.start
  const k = Math.floor((t - phase) / period)
  const since = t - (phase + k * period)
  const env = (fall: number) => since < 0.06 ? out3(since / 0.06) : Math.exp(-(since - 0.06) / fall)
  const hit = raw > 0.35 ? env(0.11) : 0
  const swing = raw > 0.35 ? (k % 2 === 0 ? 1 : -1) * 6 * env(0.3) : 0
  const s = back(win(el, 0, 0.4)) * (1 + 0.1 * hit) * (1 - gone * 0.5)
  if (s <= 0.001) return null
  ctx.save()
  ctx.globalAlpha = 1 - gone
  ctx.translate(c.x, c.y - hit * 0.06 * S)
  ctx.rotate(((lerp(-22, 0, out3(win(el, 0, 0.4))) + swing) * Math.PI) / 180)
  ctx.scale(s * S, s * S)
  sticker(ctx, g.sticker ?? 'heart', g.tint, s * S)
  ctx.restore()
  return { id: g.id, x: c.x - S * 0.6, y: c.y - S * 0.6, w: S * 1.2, h: S * 1.2 }
}

/** One sticker in a unit box (-0.5..0.5): a white die-cut edge casting one
 *  soft shadow, the shape in its colour, and its details. `px` is how big it
 *  is on screen: a canvas shadow is measured in pixels, whatever the scale. */
function sticker(ctx: Ctx, kind: StickerKind, tint: string, px: number) {
  const shape = SHAPES[kind]
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  // the white edge, with the shadow under it (cast once: the fill goes on
  // after the shadow is off, or the shadow doubles)
  ctx.shadowColor = 'rgba(0,0,0,0.38)'
  ctx.shadowBlur = 0.07 * px
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = 0.035 * px
  ctx.lineWidth = 0.11
  ctx.strokeStyle = '#ffffff'
  ctx.fillStyle = '#ffffff'
  shape(ctx)
  ctx.stroke()
  noShadow(ctx)
  ctx.fill()
  ctx.fillStyle = tint
  shape(ctx)
  ctx.fill()
  DETAIL[kind]?.(ctx, tint)
}
const SHAPES: Record<StickerKind, (ctx: Ctx) => void> = {
  heart: (ctx) => {
    ctx.beginPath()
    ctx.moveTo(0, 0.38)
    ctx.bezierCurveTo(-0.08, 0.3, -0.46, 0.08, -0.46, -0.14)
    ctx.bezierCurveTo(-0.46, -0.34, -0.3, -0.44, -0.18, -0.44)
    ctx.bezierCurveTo(-0.08, -0.44, -0.02, -0.38, 0, -0.3)
    ctx.bezierCurveTo(0.02, -0.38, 0.08, -0.44, 0.18, -0.44)
    ctx.bezierCurveTo(0.3, -0.44, 0.46, -0.34, 0.46, -0.14)
    ctx.bezierCurveTo(0.46, 0.08, 0.08, 0.3, 0, 0.38)
    ctx.closePath()
  },
  star: (ctx) => {
    ctx.beginPath()
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 0.21 : 0.48
      if (i) ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r + 0.03)
      else ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r + 0.03)
    }
    ctx.closePath()
  },
  smile: (ctx) => { ctx.beginPath(); ctx.arc(0, 0, 0.44, 0, Math.PI * 2) },
  sun: (ctx) => {
    ctx.beginPath()
    for (let i = 0; i < 16; i++) {
      const a = (i * Math.PI) / 8, r = i % 2 ? 0.36 : 0.48
      if (i) ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r)
      else ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r)
    }
    ctx.closePath()
  },
  flower: (ctx) => {
    ctx.beginPath()
    for (let i = 0; i < 5; i++) {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / 5
      ctx.moveTo(Math.cos(a) * 0.26 + 0.2, Math.sin(a) * 0.26)
      ctx.arc(Math.cos(a) * 0.26, Math.sin(a) * 0.26, 0.2, 0, Math.PI * 2)
    }
  },
  bolt: (ctx) => {
    ctx.beginPath()
    ctx.moveTo(0.08, -0.48); ctx.lineTo(-0.3, 0.06); ctx.lineTo(-0.02, 0.06)
    ctx.lineTo(-0.12, 0.48); ctx.lineTo(0.3, -0.08); ctx.lineTo(0.02, -0.08)
    ctx.closePath()
  },
  note: (ctx) => {
    ctx.beginPath()
    ctx.ellipse(-0.22, 0.28, 0.14, 0.1, -0.4, 0, Math.PI * 2)
    ctx.moveTo(0.4, 0.2)
    ctx.ellipse(0.26, 0.2, 0.14, 0.1, -0.4, 0, Math.PI * 2)
    ctx.rect(-0.12, -0.36, 0.07, 0.62)
    ctx.rect(0.36, -0.44, 0.07, 0.62)
    ctx.moveTo(-0.12, -0.36); ctx.lineTo(0.43, -0.44); ctx.lineTo(0.43, -0.28); ctx.lineTo(-0.12, -0.2); ctx.closePath()
  },
  sparkle: (ctx) => {
    ctx.beginPath()
    ctx.moveTo(0, -0.48)
    ctx.quadraticCurveTo(0.06, -0.06, 0.48, 0)
    ctx.quadraticCurveTo(0.06, 0.06, 0, 0.48)
    ctx.quadraticCurveTo(-0.06, 0.06, -0.48, 0)
    ctx.quadraticCurveTo(-0.06, -0.06, 0, -0.48)
    ctx.closePath()
  },
}
const DETAIL: Partial<Record<StickerKind, (ctx: Ctx, tint: string) => void>> = {
  smile: (ctx, tint) => {
    const ink = darkInk(tint) ? '#ffffff' : '#3a2a22'
    ctx.fillStyle = ink
    ctx.beginPath(); ctx.ellipse(-0.14, -0.1, 0.05, 0.075, 0, 0, Math.PI * 2); ctx.fill()
    ctx.beginPath(); ctx.ellipse(0.14, -0.1, 0.05, 0.075, 0, 0, Math.PI * 2); ctx.fill()
    ctx.strokeStyle = ink
    ctx.lineWidth = 0.055
    ctx.beginPath(); ctx.arc(0, 0.02, 0.22, 0.2 * Math.PI, 0.8 * Math.PI); ctx.stroke()
    ctx.fillStyle = 'rgba(214,110,110,0.4)'
    ctx.beginPath(); ctx.ellipse(-0.26, 0.1, 0.07, 0.045, 0, 0, Math.PI * 2); ctx.fill()
    ctx.beginPath(); ctx.ellipse(0.26, 0.1, 0.07, 0.045, 0, 0, Math.PI * 2); ctx.fill()
  },
  sun: (ctx) => {
    ctx.fillStyle = 'rgba(255,255,255,0.35)'
    ctx.beginPath(); ctx.arc(0, 0, 0.24, 0, Math.PI * 2); ctx.fill()
  },
  flower: (ctx) => {
    ctx.fillStyle = '#f2d58a'
    ctx.beginPath(); ctx.arc(0, 0, 0.14, 0, Math.PI * 2); ctx.fill()
    ctx.strokeStyle = 'rgba(140,100,40,0.3)'
    ctx.lineWidth = 0.02
    ctx.stroke()
  },
}

// Sparkles: a few four-pointed stars spread evenly round a spot -- one large,
// two middling, four small -- each twinkling brighter and dimmer at its own
// pace and turning slowly. A faint dark edge keeps them off a pale sky, then
// a soft glow in the piece's colour.
const SPARKLE_SIZES = [0.06, 0.04, 0.04, 0.026, 0.026, 0.026, 0.026]
const sparkles: Draw = (ctx, W, H, g, t) => {
  const { el, raw, gone } = life(g, t, 0.6, 0.4)
  const u = Math.min(W, H) * scaleOf(g)
  const c = spot(g, W, H, H > W ? { x: W * 0.5, y: H * 0.26 } : { x: W * 0.7, y: H * 0.3 })
  const R = 0.2 * u
  const rnd = seeded(g.id)
  // where they sit: the big one near the middle, the rest round it, never
  // closer than their sizes allow (the same places for this piece every time)
  const at: { x: number; y: number; size: number }[] = []
  const turn0 = rnd() * Math.PI * 2
  SPARKLE_SIZES.forEach((k, i) => {
    const size = k * u
    let best = { x: 0, y: 0, size }
    for (let tries = 0; tries < 40; tries++) {
      const a = i === 0 ? rnd() * Math.PI * 2 : turn0 + ((i - 1) / 6) * Math.PI * 2 + (rnd() - 0.5) * 0.9
      const r = i === 0 ? rnd() * 0.25 * R : (0.45 + 0.55 * rnd()) * R
      best = { x: Math.cos(a) * r, y: Math.sin(a) * r * 0.8, size }
      if (at.every((o) => Math.hypot(o.x - best.x, o.y - best.y) >= 1.3 * (o.size + size))) break
    }
    at.push(best)
  })
  // a glint: long up and down, shorter across, pinched thin
  const star = (s: number) => {
    const h = s * 0.72, a = s * 0.12, b = s * 0.02
    ctx.beginPath()
    ctx.moveTo(0, -s)
    ctx.bezierCurveTo(b, -a, a * 0.72, -b, h, 0)
    ctx.bezierCurveTo(a * 0.72, b, b, a, 0, s)
    ctx.bezierCurveTo(-b, a, -a * 0.72, b, -h, 0)
    ctx.bezierCurveTo(-a * 0.72, -b, -b, -a, 0, -s)
    ctx.fill()
  }
  ctx.save()
  ctx.fillStyle = g.tint
  at.forEach((p, i) => {
    const f = 0.6 + 0.6 * rnd(), ph0 = rnd()
    const pop = back(win(el, i * 0.07, 0.35))
    const tw = Math.abs(Math.sin(Math.PI * (raw * f + ph0))) ** 1.4
    const s = p.size * pop * (0.65 + 0.35 * tw) * (1 - gone)
    if (s <= 0.2) return
    ctx.save()
    ctx.translate(c.x + p.x, c.y + p.y)
    ctx.rotate(raw * (i % 2 ? 0.5 : -0.5) + i)
    ctx.globalAlpha = clamp01(pop) * (1 - gone) * (0.55 + 0.45 * tw)
    ctx.shadowColor = 'rgba(80,55,10,0.35)'
    ctx.shadowBlur = 0.01 * u
    star(s)
    ctx.shadowColor = g.tint
    ctx.shadowBlur = s * 0.9
    star(s)
    // a bright core, so it reads as light rather than a cut-out
    noShadow(ctx)
    const core = ctx.createRadialGradient(0, 0, 0, 0, 0, s * 0.45)
    core.addColorStop(0, 'rgba(255,255,255,0.85)')
    core.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = core
    ctx.beginPath()
    ctx.arc(0, 0, s * 0.45, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = g.tint
    ctx.restore()
  })
  ctx.restore()
  return { id: g.id, x: c.x - R, y: c.y - R * 0.8, w: 2 * R, h: 1.6 * R }
}

// Circle it: a marker loop draws itself round a spot, a little more than
// once, fast at first the way a hand starts and thinning at its end as a
// marker lifts; its words, if any, are written on above it (below, if
// there's no room above).
const circle: Draw = (ctx, W, H, g, t) => {
  const { el, gone } = life(g, t, 1.0, 0.35)
  const u = Math.min(W, H) * scaleOf(g)
  const c = spot(g, W, H, { x: W * 0.5, y: H * 0.5 })
  const rx = 0.2 * u, ry = 0.13 * u
  const rnd = seeded(g.id)
  const wob = rnd() * Math.PI * 2
  const turn = 1.13
  const p = 1 - (1 - win(el, 0.05, 0.6)) ** 2
  const N = 120
  const lw = Math.max(2, 0.013 * u)
  ctx.save()
  ctx.globalAlpha = 1 - gone
  ctx.translate(c.x, c.y)
  ctx.rotate(-0.12)
  soft(ctx, u, 0.35, 0.012, 0.003)
  const th0 = -Math.PI * 0.62
  const pt = (i: number) => {
    const f = i / N
    const th = th0 + f * turn * Math.PI * 2
    const k = 1 + 0.035 * Math.sin(3 * th + wob) + 0.06 * f
    return [Math.cos(th) * rx * k, Math.sin(th) * ry * k]
  }
  // the loop as one filled ribbon with round ends, full width until the last
  // tenth, then thinning: one shape casts one shadow and fades out cleanly
  const last = Math.floor(N * p), taper = Math.floor(N * 0.9)
  if (last >= 1) {
    const half = (i: number) => (lw / 2) * (i <= taper ? 1 : lerp(1, 0.55, (i - taper) / (N - taper)))
    const L: number[][] = [], Rt: number[][] = [], dirs: number[][] = []
    for (let i = 0; i <= last; i++) {
      const [x, y] = pt(i), [ax, ay] = pt(Math.max(0, i - 1)), [bx, by] = pt(Math.min(last, i + 1))
      const len = Math.hypot(bx - ax, by - ay) || 1
      const dx = (bx - ax) / len, dy = (by - ay) / len, w = half(i)
      dirs.push([dx, dy])
      L.push([x - dy * w, y + dx * w])
      Rt.push([x + dy * w, y - dx * w])
    }
    const cap = (i: number, back: boolean) => {
      const [x, y] = pt(i), [dx, dy] = dirs[i], w = half(i), sg = back ? -1 : 1
      for (let j = 1; j < 8; j++) {
        const a = (j / 8) * Math.PI
        ctx.lineTo(x + w * (Math.cos(a) * -dy * sg + Math.sin(a) * dx * sg), y + w * (Math.cos(a) * dx * sg + Math.sin(a) * dy * sg))
      }
    }
    ctx.fillStyle = g.tint
    ctx.beginPath()
    ctx.moveTo(L[0][0], L[0][1])
    for (let i = 1; i <= last; i++) ctx.lineTo(L[i][0], L[i][1])
    cap(last, false)
    for (let i = last; i >= 0; i--) ctx.lineTo(Rt[i][0], Rt[i][1])
    cap(0, true)
    ctx.closePath()
    ctx.fill()
  }
  ctx.restore()
  let box = { id: g.id, x: c.x - rx * 1.1, y: c.y - ry * 1.1, w: rx * 2.2, h: ry * 2.2 }
  if (g.text) {
    // written on left to right, by the same hand as the loop
    const wp = win(el, 0.6, 0.45), wrote = 1 - (1 - wp) ** 2
    ctx.save()
    ctx.globalAlpha = clamp01(wp * 4) * (1 - gone)
    const m = safe(W, H)
    const lab = fit(ctx, g.text, (q) => `700 ${q}px ${HAND}`, 0.064 * u, (W - m.l - m.r) * 0.9, 1)
    const px = lab.px
    ctx.font = `700 ${px}px ${HAND}`
    ctx.fillStyle = g.tint
    const tw = ctx.measureText(lab.rows[0]).width
    // to the right above the loop, else to the left, else over its middle,
    // always inside the safe area; under the loop if the top has no room
    const right = c.x + rx * 0.55, left = c.x - rx * 0.55 - tw
    const tx0 = right + tw <= W - m.r ? right : left >= m.l ? left : c.x - tw / 2
    const tx = Math.max(m.l, Math.min(W - m.r - tw, tx0))
    const above = c.y - ry * 1.3 - lw
    const under = above - px < m.t
    const ty = under ? Math.min(H - m.b - px, c.y + ry * 1.3 + lw) : above
    ctx.textBaseline = under ? 'top' : 'bottom'
    ctx.translate(tx + tw / 2, ty)
    ctx.rotate(-0.06)
    ctx.beginPath()
    ctx.rect(-tw / 2 - px * 0.4, under ? -px * 0.3 : -px * 1.4, (tw + px * 0.8) * wrote, px * 1.7)
    ctx.clip()
    ctx.textAlign = 'center'
    soft(ctx, u, 0.75, 0.003, 0.001)
    ctx.fillText(lab.rows[0], 0, 0)
    soft(ctx, u, 0.55, 0.016, 0.003)
    ctx.fillText(lab.rows[0], 0, 0)
    ctx.restore()
    // grown evenly round the loop's centre, so a drag moves it from where it is
    const top = under ? ty : ty - px, bottom = under ? ty + px : ty
    const dx = Math.max(c.x - Math.min(box.x, tx), Math.max(box.x + box.w, tx + tw) - c.x)
    const dy = Math.max(c.y - Math.min(box.y, top), Math.max(box.y + box.h, bottom) - c.y)
    box = { id: g.id, x: c.x - dx, y: c.y - dy, w: 2 * dx, h: 2 * dy }
  }
  return box
}

// Progress bar: a thin rounded bar across the top that fills as its stretch
// of the video plays, a dot at its head. On a vertical video it sits just
// under the app's own header, not behind it.
const progress: Draw = (ctx, W, H, g, t) => {
  const u = Math.min(W, H)
  const m = safe(W, H)
  const d = Math.max(0.01, g.shown_end - g.start)
  const p = clamp01((t - g.start) / d)
  const a = out3(win(t - g.start, 0, 0.35)) * (1 - in2(1 - clamp01((g.shown_end - t) / 0.2)))
  const x0 = Math.min(m.l, m.r), x1 = W - x0, y = H > W ? m.t : m.t * 0.42
  const h = Math.max(3, 0.009 * u * scaleOf(g))
  const e = Math.max(1, 0.0015 * u)
  ctx.save()
  ctx.globalAlpha = a
  // a dark bed under the track, so it reads over a bright sky
  ctx.fillStyle = 'rgba(0,0,0,0.22)'
  ctx.beginPath()
  ctx.roundRect(x0 - e, y - e, x1 - x0 + 2 * e, h + 2 * e, h / 2 + e)
  ctx.fill()
  ctx.fillStyle = 'rgba(255,255,255,0.28)'
  ctx.beginPath()
  ctx.roundRect(x0, y, x1 - x0, h, h / 2)
  ctx.fill()
  soft(ctx, u, 0.45, 0.006, 0.0015)
  ctx.fillStyle = g.tint
  ctx.beginPath()
  ctx.roundRect(x0, y, Math.max(h, (x1 - x0) * p), h, h / 2)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(x0 + Math.max(h / 2, (x1 - x0) * p - h / 2), y + h / 2, h * 0.95, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
  return null
}

const DRAW: Record<GraphicPiece, Draw> = { title, chapter, route, pin, camcorder, clock, stickers, sparkles, circle, progress }

/** Every graphic on screen at t, drawn over what's already on the canvas
 *  (it doesn't clear). Where each landed goes into `boxes`, for picking and
 *  dragging on the preview. */
export function drawGraphics(ctx: Ctx, W: number, H: number, items: Graphic[], t: number, boxes?: GraphicBox[]): void {
  for (const g of items) {
    if (t < g.start || t >= g.shown_end) continue
    ctx.save()
    const box = DRAW[g.piece]?.(ctx, W, H, g, t)
    ctx.restore()
    track(ctx, 0)
    if (box && boxes && !FRAMEWIDE.includes(g.piece)) boxes.push(box)
  }
}

/** Identical keys draw identical pixels (the exporter sends one PNG per run
 *  of equal keys): a moving piece changes every frame, a camcorder only when
 *  its clock or its REC dot does, a progress bar when its width moves. */
export function graphicsKey(items: Graphic[], t: number, fps = 30): string {
  const out: string[] = []
  for (const g of items) {
    if (t < g.start || t >= g.shown_end) continue
    const el = t - g.start
    if (g.piece === 'camcorder' && el > 0.25 && g.shown_end - t > 0.25) {
      const sec = filmedAt(g, t)
      out.push(`${g.id}:${sec == null ? Math.floor(el) : Math.floor(sec)}:${el % 1 < 0.62 ? 1 : 0}`)
    } else if (g.piece === 'progress' && el > 0.35 && g.shown_end - t > 0.2) {
      out.push(`${g.id}:p${Math.round((el / Math.max(0.01, g.shown_end - g.start)) * 900)}`)
    } else {
      out.push(`${g.id}:${Math.round(el * fps)}`)
    }
  }
  return out.join('|')
}

/** Which frames of the edit have a graphic on (frame numbers). */
export function graphicFrames(items: Graphic[], fps: number, total: number): number[] {
  const set = new Set<number>()
  const last = Math.round(total * fps)
  for (const g of items) {
    for (let f = Math.max(0, Math.floor(g.start * fps)); f < Math.min(last, Math.ceil(g.shown_end * fps)); f++) set.add(f)
  }
  return [...set].sort((a, b) => a - b)
}

/** A piece as the tab's tile shows it: sample words and a sample route, so
 *  every tile plays, whatever the video has. */
export function samplePiece(piece: GraphicPiece, tint?: string, sticker?: StickerKind): Graphic {
  const d = PIECES[piece].life
  const base: Graphic = { id: `tile-${piece}`, piece, text: '', sub: '', tint: tint ?? DEFAULT_TINT[piece], dur: d,
    anchor: { to: 'edit' }, at: 0, start: 0, end: d, shown_end: d, place: null }
  const words: Partial<Record<GraphicPiece, Partial<Graphic>>> = {
    title: { text: 'Sunday', sub: 'October 19' },
    chapter: { text: 'Coffee', sub: '01' },
    pin: { text: 'Soho' },
    camcorder: { text: 'Oct 19 2026', times: [[0, d, 9 * 3600 + 41 * 60 + 7, 1]] },
    clock: { clock: 9 * 60 + 30 },
    stickers: { sticker: sticker ?? 'heart', beat: { bpm: 100, phase: 0.2 } },
    route: { stops: [{ x: 0.1, y: 0.75, name: null }, { x: 0.45, y: 0.3, name: null }, { x: 0.9, y: 0.55, name: 'Here' }],
             here: 2, aspect: 1.5 },
  }
  return { ...base, ...words[piece] }
}
// On a small tile a piece sits in the middle and bigger than on the video,
// so it can be seen; the frame-wide ones (camcorder, progress) keep their
// places. `k` grows it again (a square tile is smaller than a wide one).
const TILE_SIZE: Partial<Record<GraphicPiece, number>> = {
  title: 1.8, chapter: 1.5, route: 1.2, pin: 1.6, clock: 1.6, stickers: 2.2, sparkles: 1.3, circle: 1.3,
}
export function tilePiece(piece: GraphicPiece, k = 1, tint?: string, sticker?: StickerKind): Graphic {
  const g = samplePiece(piece, tint, sticker)
  return FRAMEWIDE.includes(piece) ? g : { ...g, place: { x: 0.5, y: 0.5, scale: 1 }, size: (TILE_SIZE[piece] ?? 1) * k }
}
export const DEFAULT_TINT: Record<GraphicPiece, string> = {
  title: '#ffffff', chapter: '#f6ead7', route: '#c97b84', pin: '#c97b84', camcorder: '#ffffff',
  clock: '#c97b84', stickers: '#e8b4b8', sparkles: '#ffe08a', circle: '#c96f58', progress: '#ffffff',
}
