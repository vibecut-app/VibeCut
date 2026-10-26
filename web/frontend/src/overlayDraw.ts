// Words on screen, drawn. One function draws a frame of overlays at time t
// onto any canvas: the live preview over the player and the export renderer
// both call it, so what the creator watches is what gets exported.
//
// Everything is sized from the frame's short side and placed inside a safe
// area, so a preview canvas 400 px wide and a 1080×1920 export frame draw the
// same composition. Nothing here reads the clock or animates with CSS: the
// state at t is computed, never accumulated, which is what lets the export
// render any frame in any order.

import { fontById } from './captionFonts.ts'
import type { CaptionBackdrop, CaptionEnter, CaptionOutline, CaptionShadow, CaptionTemplate, HeadingLook, LineRole, Motion, Overlay, OverlayKind, OverlayStyle } from './types'

export type Part = { id: string; title: string; start: number; end: number }

export const KIND_META: Record<OverlayKind, { label: string; icon: string; color: string; hint: string }> = {
  title: { label: 'Title', icon: 'T', color: '#b9d9eb', hint: 'Big words that open the video' },
  part: { label: 'Part label', icon: '§', color: '#a7c4a0', hint: 'Names a part or a place as it begins' },
  name: { label: 'Name tag', icon: '◧', color: '#e8c39e', hint: 'Who is speaking, with a handle or role' },
  caption: { label: 'Caption', icon: '❝', color: '#d8d8de', hint: 'A spoken line or short remark' },
  date: { label: 'Date', icon: '◷', color: '#c4b5fd', hint: 'When it was filmed' },
  end: { label: 'End card', icon: '■', color: '#f0a8a8', hint: 'The last words, over the last seconds' },
  chapters: { label: 'Chapter bar', icon: '▭', color: '#9fb4c7', hint: 'Shows which part of the video you are in' },
  heading: { label: 'Chapter title', icon: '❡', color: '#f2b8c6', hint: 'A designed title with a plain line under it' },
}

// ---- timing ---------------------------------------------------------------

const clamp01 = (x: number) => Math.max(0, Math.min(1, x))
const easeOut = (x: number) => 1 - (1 - x) ** 3

/** CSS cubic-bezier(x1, y1, x2, y2) as a function of progress 0..1. y may
 *  overshoot past 1 (a back-out curve), which is how Playful bounces. */
export function bezier([x1, y1, x2, y2]: [number, number, number, number]): (x: number) => number {
  const at = (a: number, b: number, t: number) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
  return (x: number) => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let lo = 0, hi = 1, t = x
    for (let i = 0; i < 40; i++) {   // x(t) is monotone for 0<=x1,x2<=1: bisect
      t = (lo + hi) / 2
      if (at(x1, x2, t) < x) lo = t
      else hi = t
    }
    return at(y1, y2, t)
  }
}

/** Intro and outro lengths. The outro finishes *before* the overlay's end so
 *  it never vanishes on a hard cut -- and a short overlay doesn't spend most
 *  of its life animating. (The fade-before-end idea is Overlay Studio's.)
 *  A look sets the intro; exits mirror it at 0.6× (spec §4.4). */
export function envelope(o: Pick<Overlay, 'start' | 'shown_end'>, motion?: Motion | null): { inS: number; outS: number } {
  const d = Math.max(0, o.shown_end - o.start)
  if (!motion) return { inS: Math.min(0.5, d * 0.3), outS: Math.min(0.3, d * 0.25) }
  const inS = Math.min(motion.in_s, d * 0.35)
  return { inS, outS: Math.min(inS * 0.6, d * 0.25) }
}

/** How far in (0→1) and how far from gone (1→0) an overlay is at t. A look
 *  that steps (Cozy's 12 fps paper card, Film's 8 fps) holds each step. */
export function phase(o: Pick<Overlay, 'start' | 'shown_end'>, t: number, motion?: Motion | null): { on: boolean; pin: number; pout: number } {
  if (t < o.start || t >= o.shown_end) return { on: false, pin: 0, pout: 0 }
  const { inS, outS } = envelope(o, motion)
  let el = t - o.start
  if (motion && motion.step_fps > 0 && el < inS) el = Math.floor(el * motion.step_fps + 1e-6) / motion.step_fps
  return {
    on: true,
    pin: inS > 0 ? clamp01(el / inS) : 1,
    pout: outS > 0 ? clamp01((o.shown_end - t) / outS) : 1,
  }
}

/** How one line group of a block looks at intro progress `pin` (0..1): the
 *  look's curve, its stagger between groups, and its entrance. */
export type Pose = { dx: number; dy: number; alpha: number; scale: number; rot: number }
export function pose(o: Pick<Overlay, 'anim' | 'kind' | 'start' | 'shown_end'>, pin: number, pout: number, group: number,
  u: number, align: CanvasTextAlign, motion?: Motion | null): Pose {
  const ease = motion ? bezier(motion.curve) : easeOut
  const { inS } = envelope(o, motion)
  const lag = motion && inS > 0 ? (group * motion.stagger_s) / inS : 0
  const p = clamp01((pin - lag) / Math.max(1e-6, 1 - Math.min(lag, 0.9)))
  const e = ease(p)
  const big = o.kind === 'title' || o.kind === 'end' || o.kind === 'part' || o.kind === 'heading'
  const typing = o.anim === 'type'
  let alpha = (typing ? Math.min(1, p * 4) : clamp01(e)) * pout
  let dx = 0, dy = 0, scale = 1, rot = 0
  const ce = motion?.caption_enter
  if (ce) {
    // a caption template's entrance (the Animation tab), for captions only
    if (ce === 'fade') { dy = (1 - e) * 0.035 * u; alpha = clamp01(e) * pout }
    else if (ce === 'pop') { scale = Math.max(0.02, e); alpha = Math.min(1, p * 4) * pout }
    else if (ce === 'slide') { dx = -(1 - e) * 0.14 * u; alpha = Math.min(1, p * 2.5) * pout }
    else if (ce === 'stamp') { scale = 1 + (1 - e) * 1.1; rot = (-(1 - e) * 4 * Math.PI) / 180; alpha = Math.min(1, p * 3) * pout }
    else alpha = (p > 0 ? 1 : 0) * pout   // type, word: the words appear; nothing moves
    return { dx, dy, alpha, scale, rot }
  }
  if (big && motion?.enter === 'slam') {            // Hype: in from 1.5×, fast
    scale = 1.5 - 0.5 * e
    alpha = Math.min(1, p * 3) * pout
  } else if (big && motion?.enter === 'card') {     // Cozy: the measured paper-card path
    dy = (1 - e) * 0.024 * u
    rot = ((5 - 7 * e) * Math.PI) / 180
    scale = 0.88 + 0.12 * e
  } else {
    dx = o.anim === 'slide' ? (1 - e) * 0.05 * u * (align === 'right' ? 1 : -1) : 0
    dy = o.anim === 'rise' ? (1 - e) * 0.035 * u : 0
  }
  return { dx, dy, alpha, scale, rot }
}

export function partAt(parts: Part[], t: number): number {
  for (let i = parts.length - 1; i >= 0; i--) if (parts[i].start <= t) return i
  return 0
}

/** Identical keys draw identical pixels. The exporter sends one frame per
 *  run of equal keys -- a title holding still is one PNG with a duration. */
export function frameKey(items: Overlay[], parts: Part[], t: number, motion?: Motion | null, style?: OverlayStyle | null): string {
  const out: string[] = []
  for (const o of items) {
    const p = phase(o, t, style ? motionFor(o, style) : motion)
    if (!p.on) continue
    out.push(`${o.id}:${Math.round(p.pin * 1000)}:${Math.round(p.pout * 1000)}${o.kind === 'chapters' ? `:${partAt(parts, t)}` : ''}`)
  }
  return out.join('|')
}

/** Which frames of the edit have anything on screen (frame numbers). */
export function busyFrames(items: Overlay[], fps: number, total: number): number[] {
  const set = new Set<number>()
  const last = Math.round(total * fps)
  for (const o of items) {
    const a = Math.max(0, Math.floor(o.start * fps))
    const z = Math.min(last, Math.ceil(o.shown_end * fps))
    for (let f = a; f < z; f++) set.add(f)
  }
  return [...set].sort((x, y) => x - y)
}

// ---- type -----------------------------------------------------------------

const FAMILY: Record<OverlayStyle['font'], string> = {
  Clean: 'system-ui, -apple-system, "Helvetica Neue", "PingFang SC", "Hiragino Sans", sans-serif',
  Editorial: '"EB Garamond", "Songti SC", "Hiragino Mincho ProN", serif',
  Rounded: '"Nunito", "PingFang SC", "Hiragino Maru Gothic ProN", sans-serif',
  // Film's typewriter and Hype's condensed caps, from fonts every Mac has
  Mono: '"Courier Prime", "Courier New", ui-monospace, Menlo, "PingFang SC", monospace',
  Condensed: '"Anton", Impact, "Arial Narrow", "Helvetica Neue", "PingFang SC", sans-serif',
}
const WEIGHT: Record<OverlayStyle['font'], { bold: number; regular: number }> = {
  Clean: { bold: 700, regular: 500 }, Editorial: { bold: 600, regular: 500 }, Rounded: { bold: 800, regular: 600 },
  Mono: { bold: 700, regular: 400 }, Condensed: { bold: 400, regular: 400 },
}
export const fontCss = (style: OverlayStyle, px: number, bold: boolean) =>
  `${bold ? WEIGHT[style.font].bold : WEIGHT[style.font].regular} ${Math.round(px)}px ${FAMILY[style.font]}`
const lineFont = (style: OverlayStyle, ln: Line, px = ln.px) =>
  ln.family ? `${ln.italic ? 'italic ' : ''}${ln.weight ?? 700} ${Math.round(px)}px ${ln.family}` : fontCss(style, px, ln.bold)

/** Web fonts must be loaded before a canvas can draw them. */
export async function ensureFonts(style: OverlayStyle): Promise<void> {
  if (typeof document === 'undefined' || !document.fonts) return
  const tpl = tplFor(style)
  const face = fontById(style.typeface)
  const fonts = [fontCss(style, 40, true), fontCss(style, 40, false), ...(tpl ? [`${tpl.weight} 40px ${tpl.family}`] : []),
    ...Object.values(HEADINGS).flatMap((h) => [`${h.weight} 40px ${h.family}`, `${h.italic ? 'italic ' : ''}${h.sub.weight} 40px ${h.sub.family}`]),
    ...(face ? [`${face.weight} 40px ${face.family}`] : [])]
  await Promise.all(fonts.map((f) => document.fonts.load(f).catch(() => [])))
}

// ---- caption templates ----------------------------------------------------
//
// How every caption in the video is dressed (the Style tab when a caption is
// clicked; overlays.TEMPLATES). Each one carries its own way of being read
// over any frame -- a black edge, a backing, a marker band -- so the
// contrast fix (ink.py) only matters for the two that are bare letters.
// Fonts: what every Mac already has, first (CLAUDE.md: never bundle a font).

type Tpl = {
  family: string; weight: number; size: number; color: string
  case?: 'upper' | 'lower'; track?: number
  stroke?: { color: string; w: number }            // edge width as a share of the letter size
  box?: { fill: string; ink: string; round: number }   // a backing per line; round as a share of its height
  marker?: { band: string; ink: string }           // a highlighter stroke behind each line
  shadow?: boolean | { color: string; blur: number; dist: number }   // blur and distance as shares of the letter size
  glow?: { color: string; blur: number }           // neon: coloured light around the letters
  gradient?: [string, string]                      // letters filled top to bottom
  extrude?: { color: string; depth: number; solid?: boolean }   // 3D sides, or one hard drop when solid
  thick?: number                                   // heavier letters: a stroke in their own colour
  split?: boolean                                  // "7:42 am · coffee run": the time on its own line, on top
  pop?: string[]                                   // the longest words in colour
  rule?: boolean                                   // a thin line above
  softSub?: boolean                                // the place name in the same quiet case, not spaced capitals
  side?: 'left'                                    // sits to one side, low, rather than centred
}
const SERIF = '"Times New Roman", "EB Garamond", Georgia, "Songti SC", serif'
const SANS = '"Helvetica Neue", Helvetica, Arial, "PingFang SC", sans-serif'
export const TEMPLATES: Record<CaptionTemplate, Tpl> = {
  outlined: { family: SERIF, weight: 700, size: 0.064, color: '#ffffff', stroke: { color: '#000000', w: 0.13 }, split: true },
  bold: { family: `"Avenir Next", "Avenir", ${SANS}`, weight: 800, size: 0.066, color: '#ffffff', case: 'upper',
          stroke: { color: '#000000', w: 0.2 }, split: true },
  label: { family: SANS, weight: 700, size: 0.048, color: '#141414', box: { fill: '#ffffff', ink: '#141414', round: 0.5 } },
  highlight: { family: SANS, weight: 700, size: 0.052, color: '#141414', marker: { band: '#ffe14d', ink: '#141414' } },
  handwritten: { family: '"Bradley Hand", "Noteworthy", "Marker Felt", "Segoe Print", cursive', weight: 700, size: 0.07,
                 color: '#fff8ec', case: 'lower', shadow: true },
  tape: { family: '"American Typewriter", "Courier New", "Courier Prime", monospace', weight: 600, size: 0.044,
          color: '#222222', box: { fill: '#f4efe3', ink: '#222222', round: 0.08 } },
  pop: { family: `"Arial Rounded MT Bold", "Nunito", "Avenir Next", ${SANS}`, weight: 800, size: 0.066, color: '#ffffff',
         stroke: { color: '#1a1a1a', w: 0.18 }, pop: ['#ffd84d', '#7fe0ff'], split: true },
  quiet: { family: SANS, weight: 400, size: 0.03, color: '#ffffff', case: 'upper', track: 0.3, shadow: true, rule: true },
  // word art (sarah, 2026-10-18): each reads over any frame by its own light, edge or sides
  neon: { family: '"VC Pacifico", cursive', weight: 400, size: 0.07, color: '#fff4fd', glow: { color: '#ff2fd0', blur: 0.45 },
          stroke: { color: '#ff7ae6', w: 0.04 } },
  glow: { family: '"VC TikTok Sans", sans-serif', weight: 800, size: 0.06, color: '#ffffff', glow: { color: '#3fc8ff', blur: 0.5 } },
  gradient: { family: '"VC Montserrat", sans-serif', weight: 800, size: 0.064, color: '#ffd84d', gradient: ['#ffe259', '#ff5fa2'],
              stroke: { color: '#1a1a1a', w: 0.14 }, split: true },
  extrude: { family: '"VC Luckiest Guy", cursive', weight: 400, size: 0.068, color: '#ffd84d', stroke: { color: '#1a1a1a', w: 0.08 },
             extrude: { color: '#1a1a1a', depth: 0.1 } },
  retro: { family: '"VC Bebas Neue", sans-serif', weight: 400, size: 0.085, color: '#ffffff', track: 0.04,
           extrude: { color: '#ff4d6d', depth: 0.07, solid: true } },
}

// A colour picked by hand dresses the template: the letters of an edged or
// bare one, the backing or band of a boxed or marked one (its words then go
// black or white, whichever reads). The edge flips to white under dark
// letters, and a bare template gains one, so a dark pick still reads over
// dark footage (sarah: captions must contrast with the footage).
const dark = (hex: string) => {
  const n = parseInt(hex.slice(1), 16)
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] < 0.35
}
export function tinted(tpl: Tpl, c: string | null | undefined): Tpl {
  if (!c) return tpl
  const on = dark(c) ? '#ffffff' : '#141414'
  if (tpl.box) return { ...tpl, color: on, box: { ...tpl.box, fill: c, ink: on } }
  if (tpl.marker) return { ...tpl, color: on, marker: { band: c, ink: on } }
  const edge = dark(c) ? '#ffffff' : '#000000'
  if (tpl.stroke) return { ...tpl, color: c, stroke: { ...tpl.stroke, color: edge } }
  return dark(c) ? { ...tpl, color: c, stroke: { color: edge, w: 0.1 }, shadow: false } : { ...tpl, color: c }
}
const rgba = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}
const DRESS_KEYS = ['outline', 'shadow', 'backdrop', 'thick'] as const
export const isDressed = (style: OverlayStyle) => DRESS_KEYS.some((k) => style[k] != null)

/** A template with the outline, shadow, background and weight set by hand
 *  (the Captions tab's sliders) laid over its own; the colour too. */
export function dress(tpl0: Tpl, style: OverlayStyle): Tpl {
  const bd = style.backdrop
  let t: Tpl = !bd ? tinted(tpl0, style.text_color)
    : { ...tpl0, color: style.text_color ?? tpl0.color, marker: undefined,
        box: bd.opacity > 0 ? { fill: rgba(bd.color, bd.opacity), ink: style.text_color ?? tpl0.color, round: bd.round } : undefined }
  const ol = style.outline, sh = style.shadow
  if (ol) t = { ...t, stroke: ol.width > 0 ? { color: ol.color, w: ol.width } : undefined }
  if (sh) t = { ...t, shadow: sh.opacity > 0 ? { color: rgba(sh.color, sh.opacity), blur: sh.blur, dist: sh.dist } : false }
  if (style.thick != null) t = { ...t, thick: style.thick || undefined }
  return t
}

/** What the sliders start from: the outline, shadow, background and weight
 *  the captions have now, whether set by hand or the template's own. */
export function dressOf(style: OverlayStyle): { outline: CaptionOutline; shadow: CaptionShadow; backdrop: CaptionBackdrop; thick: number } {
  const t = style.template ? dress(TEMPLATES[style.template], style) : dress(softTpl({ ink: '' } as Overlay, style), style)
  const sh = typeof t?.shadow === 'object' ? t.shadow : null
  return {
    outline: style.outline ?? { color: t?.stroke && t.stroke.color !== '#1a1a1a' ? t.stroke.color : '#000000', width: t?.stroke?.w ?? 0 },
    shadow: style.shadow ?? (sh ? { color: '#000000', opacity: 0.7, blur: sh.blur, dist: sh.dist }
      : { color: '#000000', opacity: t && !t.shadow ? 0 : 0.7, blur: 0.4, dist: 0.06 }),
    backdrop: style.backdrop ?? (t?.box ? { color: t.box.fill.startsWith('#') ? t.box.fill : '#000000', opacity: 1, round: t.box.round }
      : { color: '#000000', opacity: 0, round: 0.25 }),
    thick: style.thick ?? 0,
  }
}

// A chapter title's own look (story.py). Day vlogs title a chapter in thin,
// white, widely spaced capitals with a small line under it in the same
// family, often italic, the same way all through the video (sarah,
// 2026-10-19: titles that are "cool and aesthetic"; a red spaced title ran
// off her frame as "SCHOO"). Spaced is that look and the default; the
// others stay for picking by hand. Its look is its own, not the captions'
// one style, so a designed title and plain words can share a frame. A title
// always fits the frame on one line: it gets smaller rather than wrap, run
// off or lose letters (drawBlock, fitTitle). Bundled open fonts only.
const MONT = '"VC Montserrat", "Helvetica Neue", Helvetica, Arial, sans-serif'
const HEADING_SHADOW = { color: 'rgba(0,0,0,0.5)', blur: 0.4, dist: 0.05 }   // soft, like the quiet captions
const QUIET_SUB: Tpl = { family: MONT, weight: 300, size: 0.032, color: '#ffffff', track: 0.03, shadow: true }
type Heading = Tpl & { sub: Tpl; italic?: boolean }      // italic: the line under the title
export const HEADINGS: Record<HeadingLook, Heading> = {
  spaced: { family: MONT, weight: 300, size: 0.062, color: '#ffffff', case: 'upper', track: 0.42, shadow: HEADING_SHADOW,
            sub: { ...QUIET_SUB, size: 0.03, shadow: HEADING_SHADOW }, italic: true },
  script: { family: '"VC Pacifico", cursive', weight: 400, size: 0.088, color: '#ffffff', shadow: true, sub: QUIET_SUB, italic: true },
  bold: { family: '"VC Anton", Impact, sans-serif', weight: 400, size: 0.1, color: '#ffffff', case: 'upper',
          stroke: { color: '#000000', w: 0.07 }, shadow: true, sub: QUIET_SUB, italic: true },
  serif: { family: '"VC Playfair Display", Georgia, serif', weight: 700, size: 0.08, color: '#fff8ec', shadow: true, sub: QUIET_SUB, italic: true },
}
export const HEADING_DEFAULT: HeadingLook = 'spaced'

function headingLines(o: Overlay, u: number): Line[] {
  const s = SIZE[o.size]
  const t = HEADINGS[o.look ?? HEADING_DEFAULT] ?? HEADINGS[HEADING_DEFAULT]
  const line = (tpl: Tpl, text: string, px: number, italic = false): Line =>
    ({ text: tpl.case === 'lower' ? text.toLowerCase() : text, px, bold: true, family: tpl.family, weight: tpl.weight,
       color: tpl.color, track: tpl.track, upper: tpl.case === 'upper', tpl, italic, title: tpl === t })
  return [line(t, o.text, t.size * u * s), ...(o.sub ? [line(t.sub, o.sub, t.sub.size * u * s, !!t.italic)] : [])]
}

// How much smaller a chapter title must be to sit on one line in `maxW`
// (1 = as it is), never below `min`; tracking scales with the letters.
const TITLE_MIN = 0.4
export function fitTitle(measure: (text: string, px: number) => number, text: string, px: number, maxW: number,
  min = TITLE_MIN): number {
  for (let k = 1; k > min; k *= 0.94) {
    if (measure(text, px * k) <= maxW) return k
  }
  return min
}
// The floor is 40% of the title's plain size: one sized up by hand can come
// all the way back down to fit, rather than wrap or run off the frame.
const titleFloor = (o: Overlay) => Math.min(TITLE_MIN, TITLE_MIN / ((o.place?.scale ?? 1) * SIZE[o.size]))

const tplFor = (style: OverlayStyle): Tpl | null => style.template ? dress(TEMPLATES[style.template], style) : null

// Captions with no template picked: the quiet vlog caption (sarah,
// 2026-10-19, after looking at how day-in-my-life vlogs and Shorts caption:
// small, lowercase, a few words, one font, white or cream with a soft shadow,
// off to one side, so the picture stays the hero). The look's own lettering
// and the colour ink.py picked so it reads over the frame; anything set by
// hand (outline, shadow, background) lays over it.
const SOFT_SHADOW = { color: 'rgba(0,0,0,0.5)', blur: 0.35, dist: 0.04 }
export const softTpl = (o: Overlay, style: OverlayStyle): Tpl => ({
  family: FAMILY[style.font], weight: WEIGHT[style.font].regular, size: 0.05, color: o.ink || style.color,
  case: 'lower', shadow: SOFT_SHADOW, softSub: true, side: 'left',
})

// The time at the head of a describing caption, "7:42 am · coffee run".
const TIME_HEAD = /^(\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?)\s*[·•\-–—|]\s*(.+)$/i

function templateLines(o: Overlay, tpl: Tpl, u: number, chars: number): Line[] {
  const s = SIZE[o.size]
  const base = { bold: true, family: tpl.family, weight: tpl.weight, color: tpl.color, track: tpl.track, tpl }
  const cased = (x: string) => tpl.case === 'lower' ? x.toLowerCase() : x
  const upper = tpl.case === 'upper'
  const out: Line[] = []
  if (o.sub) {
    out.push(tpl.softSub ? { ...base, text: cased(o.sub), px: tpl.size * 0.72 * u * s, color: tpl.color, track: 0.02 }
      : { ...base, text: cased(o.sub), px: tpl.size * 0.5 * u * s, upper: true, track: (tpl.track ?? 0) + 0.12 })
  }
  // Typed or word-by-word: `chars` of the whole text show, split the same way
  // as the finished caption so nothing jumps from one line to two.
  const m = tpl.split ? TIME_HEAD.exec(o.text) : null
  if (m) {
    const at = o.text.lastIndexOf(m[2])
    const time = m[1].slice(0, chars), said = chars > at ? m[2].slice(0, chars - at) : ''
    out.push({ ...base, text: time, px: tpl.size * 0.9 * u * s, upper })
    if (said) out.push({ ...base, text: cased(said), px: tpl.size * u * s, upper })
  } else {
    out.push({ ...base, text: cased(o.text.slice(0, chars)), px: tpl.size * u * s, upper })
  }
  return out.filter((ln) => ln.text)
}

/** The caption's own motion when the creator picked an entrance (the
 *  Animation tab): how long it takes and its curve. Everything else keeps
 *  the look's motion. */
const ENTER: Record<CaptionEnter, { curve: Motion['curve']; in_s: (o: Overlay) => number; stagger_s: number }> = {
  fade: { curve: [0.22, 1, 0.36, 1], in_s: () => 0.5, stagger_s: 0.08 },
  pop: { curve: [0.34, 1.56, 0.64, 1], in_s: () => 0.45, stagger_s: 0.06 },
  slide: { curve: [0.16, 1, 0.3, 1], in_s: () => 0.5, stagger_s: 0.08 },
  stamp: { curve: [0.2, 0.9, 0.3, 1], in_s: () => 0.32, stagger_s: 0 },
  type: { curve: [0, 0, 1, 1], in_s: (o) => Math.min(1.6, 0.045 * o.text.length), stagger_s: 0 },
  word: { curve: [0, 0, 1, 1], in_s: (o) => Math.min(2.4, 0.3 * o.text.split(/\s+/).length), stagger_s: 0 },
}
// A chapter title moves its own way, whatever the video's look: it fades up
// and settles straight, its line a beat behind -- no card tilt, no slam,
// which would fight the thin spaced capitals.
const HEADING_MOTION: Motion = { curve: [0.16, 1, 0.3, 1], in_s: 0.7, step_fps: 0, stagger_s: 0.18, enter: null,
  case: 'sentence', track: 0, beat_lock: false }

export function motionFor(o: Overlay, style: OverlayStyle): Motion | null {
  const m = style.motion ?? null
  if (o.kind === 'heading') return HEADING_MOTION
  if (o.kind !== 'caption' || !style.enter) return m
  const e = ENTER[style.enter]
  return { case: m?.case ?? 'sentence', track: m?.track ?? 0, beat_lock: !!m?.beat_lock,
           curve: e.curve, in_s: e.in_s(o), step_fps: 0, stagger_s: e.stagger_s, enter: null, caption_enter: style.enter }
}

/** How much of the caption's words show at intro progress pin, for the
 *  entrances that write themselves out. */
function shownChars(o: Overlay, style: OverlayStyle, pin: number): number {
  const n = o.text.length
  const how = o.kind === 'caption' && style.enter ? style.enter : o.anim === 'type' ? 'type' : null
  if (how === 'type') return style.enter ? Math.ceil(n * clamp01(pin)) : Math.ceil(n * clamp01(pin * 1.6))
  if (how === 'word') {
    const words = o.text.split(/(\s+)/)
    const count = words.filter((w) => w.trim()).length
    let want = Math.max(1, Math.ceil(count * clamp01(pin))), k = 0, out = ''
    for (const w of words) { if (w.trim()) { if (k === want) break; k++ } out += w }
    return out.trimEnd().length
  }
  return n
}

const SIZE = { S: 0.78, M: 1, L: 1.4 }

// ---- layout ---------------------------------------------------------------

type Line = { text: string; px: number; bold: boolean; color: string; track?: number; upper?: boolean
  family?: string; weight?: number; tpl?: Tpl
  italic?: boolean; title?: boolean }      // a chapter title's line under it; the title itself (one line, fitted)

export function safe(W: number, H: number) {
  const portrait = H > W
  // Vertical video is watched in apps whose buttons sit bottom and right.
  return { l: W * 0.07, r: W * (portrait ? 0.14 : 0.07), t: H * (portrait ? 0.09 : 0.08), b: H * (portrait ? 0.2 : 0.09) }
}


export function wrap(measure: (s: string) => number, text: string, maxW: number, maxLines = 3): string[] {
  const tokens = text.match(/[぀-ヿ㐀-鿿가-힯][，。！？、,.!?」』]?|[^\s぀-ヿ㐀-鿿가-힯]+|\s+/g) ?? []
  const lines: string[] = []
  let cur = ''
  for (const tok of tokens) {
    const next = cur + tok
    if (cur.trim() && measure(next.trimEnd()) > maxW) {
      lines.push(cur.trimEnd())
      cur = tok.trimStart()
    } else cur = next
  }
  if (cur.trim()) lines.push(cur.trim())
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = kept[maxLines - 1].replace(/\s*\S?$/, '') + '…'
    return kept
  }
  return lines
}

// The words the video writes for itself (a stop's line, the title, the
// sign-off, a name) take the Captions panel's look too, the way CapCut's text
// panel edits whatever text is picked (sarah, 2026-10-20: the colour, shadow
// and font did nothing on a made video's "Columbia University, morning",
// which is a part label). Until something is set they keep the look's own.
const LABELS: Partial<Record<Overlay['kind'], number>> = { part: 0.058, title: 0.09, end: 0.07, name: 0.05 }

function labelTpl(o: Overlay, style: OverlayStyle): Tpl | null {
  const size = LABELS[o.kind]
  if (!size || !(style.template || isDressed(style))) return null
  // a template is sized for a caption: a label keeps its own size beside it
  if (style.template) {
    const t = tplFor(style)!
    return { ...t, size: t.size * (size / LABELS.part!), side: undefined }
  }
  return dress({ family: FAMILY[style.font], weight: WEIGHT[style.font].bold, size, color: style.text_color || o.ink || style.color, shadow: true }, style)
}

// A title and the line under it (or a caption and its place name) are a
// group: they move and time together, and each line can be tuned on its own
// (sarah, 2026-10-20: "make them into a group of captions, and we can tune it
// independently", like CapCut's grouped text). Which line is which: the place
// name sits above a caption or a stop's line, the line under a title below.
// which line of the group; tuned on its own; nudged (px)
type Grouped = Line & { role?: LineRole; own?: boolean; dx?: number; dy?: number }
export const subAbove = (o: Overlay) => o.kind === 'caption' || o.kind === 'part'
/** What each line of a group is called in the panel: "Title" / "Line under", "Words" / "Place name". */
export const lineLabel = (o: Pick<Overlay, 'kind'> | undefined, role: LineRole) =>
  o && subAbove(o as Overlay) ? (role === 'main' ? 'Words' : 'Place name') : role === 'main' ? 'Title' : 'Line under'
export const lineName = (o: Pick<Overlay, 'kind'> | undefined, role: LineRole) =>
  o && subAbove(o as Overlay) ? (role === 'main' ? 'the words' : 'the place name') : role === 'main' ? 'the title' : 'the line under the title'
function roles(o: Overlay, lines: Line[]): Grouped[] {
  if (!o.sub) return lines.map((ln): Grouped => ({ ...ln, role: 'main' }))
  const sub = subAbove(o) ? 0 : lines.length > 1 ? lines.length - 1 : -1
  return lines.map((ln, i): Grouped => ({ ...ln, role: i === sub ? 'sub' : 'main' }))
}

// One line's own look over the group's: the panel's font, colour, outline,
// shadow, background and boldness, its size, and where it sits.
function tuned(o: Overlay, style: OverlayStyle, lines: Grouped[], u: number): Grouped[] {
  if (!o.lines) return lines
  return lines.map((ln0) => {
    const L = o.lines?.[ln0.role ?? 'main']
    if (!L) return ln0
    let ln: Grouped = { ...ln0, family: ln0.family ?? FAMILY[style.font], weight: ln0.weight ?? (ln0.bold ? WEIGHT[style.font].bold : WEIGHT[style.font].regular) }
    const face = fontById(L.typeface)
    if (face) ln = { ...ln, family: face.family, weight: face.weight, px: ln.px * face.size }
    if (L.scale) ln = { ...ln, px: ln.px * L.scale }
    if (L.text_color) ln = { ...ln, color: L.text_color }
    if (L.text_color || DRESS_KEYS.some((k) => L[k] != null)) {
      const base: Tpl = ln.tpl ?? { family: ln.family!, weight: ln.weight!, size: 0, color: ln.color, track: ln.track, shadow: true }
      const tpl = dress({ ...base, family: ln.family!, weight: ln.weight! }, L as OverlayStyle)
      ln = { ...ln, tpl, color: L.text_color ?? (tpl.box ? tpl.box.ink : ln.color), own: true }
    }
    return { ...ln, dx: (L.dx ?? 0) * u, dy: (L.dy ?? 0) * u }
  })
}

function linesFor(o: Overlay, style: OverlayStyle, u: number, chars: number): Line[] {
  return tuned(o, style, roles(o, groupLines(o, style, u, chars)), u)
}

function groupLines(o: Overlay, style: OverlayStyle, u: number, chars: number): Line[] {
  const face = o.kind === 'caption' || LABELS[o.kind] ? fontById(style.typeface) : null
  // a picked font letters every caption line; the template keeps its edge,
  // backing and case, the look its colour and motion
  const lettered = (lines: Line[]) => !face ? lines
    : lines.map((ln) => ({ ...ln, family: face.family, weight: face.weight, px: ln.px * face.size }))
  if (o.kind === 'heading') return headingLines(o, u)
  if (o.kind === 'caption' && style.template) {
    return lettered(templateLines(o, tplFor(style)!, u, chars))
  }
  if (o.kind === 'caption') {
    return lettered(templateLines(o, dress(softTpl(o, style), style), u, chars))
  }
  const label = labelTpl(o, style)
  if (label) return lettered(templateLines(o, label, u, chars))
  const lines = baseLines(o, style, u, chars)
  const m = style.motion
  if (!m || o.kind === 'date') return lettered(lines)
  // the look's case and tracking, on every line (a date keeps its own)
  return lettered(lines).map((ln) => ({
    ...ln,
    text: m.case === 'lower' ? ln.text.toLowerCase() : ln.text,
    upper: ln.upper || m.case === 'upper',
    track: (ln.track ?? 0) + (o.kind === 'caption' ? 0 : m.track),
  }))
}

function baseLines(o: Overlay, style: OverlayStyle, u: number, chars: number): Line[] {
  const s = SIZE[o.size]
  const text = chars < o.text.length ? o.text.slice(0, chars) : o.text
  const ink = ((o.kind === 'caption' || LABELS[o.kind]) && style.text_color) || o.ink || style.color
  style = o.ink2 ? { ...style, accent: o.ink2 } : style
  switch (o.kind) {
    case 'title':
      return [{ text, px: 0.09 * u * s, bold: true, color: ink },
        ...(o.sub ? [{ text: o.sub, px: 0.034 * u * s, bold: false, color: ink }] : [])]
    case 'end':
      return [{ text, px: 0.07 * u * s, bold: true, color: ink },
        ...(o.sub ? [{ text: o.sub, px: 0.032 * u * s, bold: false, color: style.accent }] : [])]
    case 'part':
      return [...(o.sub ? [{ text: o.sub, px: 0.024 * u * s, bold: true, color: style.accent, track: 0.18, upper: true }] : []),
        { text, px: 0.058 * u * s, bold: true, color: ink }]
    case 'name':
      return [{ text, px: 0.05 * u * s, bold: true, color: ink },
        ...(o.sub ? [{ text: o.sub, px: 0.03 * u * s, bold: false, color: style.accent }] : [])]
    case 'caption':
      // a describing caption names the place where a new one starts, small, above the line
      return [...(o.sub ? [{ text: o.sub, px: 0.026 * u * s, bold: true, color: style.accent, track: 0.12, upper: true }] : []),
        { text, px: 0.046 * u * s, bold: false, color: ink }]
    case 'date':
      return [{ text, px: 0.03 * u * s, bold: true, color: ink, track: 0.12, upper: true }]
    default:
      return []
  }
}

type Anchor = { x: number; align: CanvasTextAlign; v: 'top' | 'middle' | 'bottom'; y: number }

function anchorFor(pos: Overlay['pos'], W: number, H: number): Anchor {
  const m = safe(W, H)
  const [row, col] = pos === 'center' ? ['middle', 'center'] : pos.includes('-')
    ? pos.split('-') as [string, string]
    : pos === 'top' || pos === 'bottom' ? [pos, 'center'] : ['middle', pos]
  const x = col === 'left' ? m.l : col === 'right' ? W - m.r : W / 2
  const align: CanvasTextAlign = col === 'left' ? 'left' : col === 'right' ? 'right' : 'center'
  const v = row === 'top' ? 'top' : row === 'bottom' ? 'bottom' : 'middle'
  const y = v === 'top' ? m.t : v === 'bottom' ? H - m.b : H / 2
  return { x, align, v, y }
}

// ---- typing on the picture --------------------------------------------------

// A chapter title typed on the picture is as small as the canvas draws it,
// so the box shows what the frame will (the frame's size in CSS pixels).
let measurer: CanvasRenderingContext2D | null = null
function fitTyped(lines: Line[], o: Overlay, style: OverlayStyle, frame: { W: number; H: number } | undefined): Line[] {
  const t = lines[0]
  if (!t?.title || !frame || typeof document === 'undefined') return lines
  measurer ??= document.createElement('canvas').getContext('2d')
  const ctx = measurer
  if (!ctx) return lines
  const { W, H } = frame
  const k = fitTitle((s, px) => {
    ctx.font = lineFont(style, t, px)
    setTracking(ctx, t.track ? t.track * px : 0)
    return ctx.measureText(t.upper ? s.toUpperCase() : s).width
  }, t.text, t.px, roomFor(o, W, H) - extra(t), titleFloor(o))
  return k === 1 ? lines : [{ ...t, px: t.px * k }, ...lines.slice(1)]
}
//
// How a caption's lines look, as CSS, for the box it's typed into on the
// preview (sarah, 2026-10-18: keep the caption's own font while editing the
// words, so she sees what she'll get). Same lines, sizes, colours, edges and
// backings the canvas draws; `u` is the frame's short side in CSS pixels.
export type TypeLine = { font: string; color: string; track: number; upper: boolean; lower: boolean; px: number; lh: number
  stroke?: { color: string; w: number }; band?: { fill: string; radius: number; padX: number }; shadow: string }
export type TypeLook = { lead: TypeLine | null; main: TypeLine; trail: TypeLine | null; backing: string | null; align: 'left' | 'center' }

export function typeLook(o: Overlay, style: OverlayStyle, u: number, frame?: { W: number; H: number }): TypeLook {
  const su = u * (o.place?.scale ?? 1)
  const probe = { ...o, sub: o.sub || ' ', text: o.text || ' ' }
  const lines = fitTyped(linesFor(probe, style, su, Infinity), o, style, frame)
  const tpl = lines[0]?.tpl
  const shadow = tpl && !tpl.shadow ? 'none'
    : tpl && !o.halo ? `0 ${0.003 * u}px ${0.02 * u}px rgba(0,0,0,0.7)`
    : o.halo ? `0 0 ${0.005 * u}px ${o.halo}, 0 ${0.002 * u}px ${0.022 * u}px ${o.halo}`
    : style.backing === 'shadow' ? `0 ${0.003 * u}px ${0.018 * u}px rgba(0,0,0,0.6)` : 'none'
  const css = (ln: Line): TypeLine => {
    const t = ln.tpl
    const px = ln.px
    // word art and a hand-set shadow, as CSS text-shadows of the same size
    const art = t?.glow ? `0 0 ${px * t.glow.blur * 0.4}px ${t.glow.color}, 0 0 ${px * t.glow.blur}px ${t.glow.color}`
      : t?.extrude ? Array.from({ length: t.extrude.solid ? 1 : 6 }, (_, i) => {
          const o = (px * t.extrude!.depth * (i + 1)) / (t.extrude!.solid ? 1 : 6)
          return `${o}px ${o}px 0 ${t.extrude!.color}`
        }).join(', ')
      : t && typeof t.shadow === 'object' && !haloWins(o) ? `${t.shadow.dist * px * 0.7071}px ${t.shadow.dist * px * 0.7071}px ${t.shadow.blur * px}px ${t.shadow.color}`
      : null
    const sw = (t?.stroke?.w ?? 0) + (t?.thick ?? 0)
    return {
      font: lineFont(style, ln), color: t?.gradient ? t.gradient[0] : ln.color, track: (ln.track ?? 0) * ln.px, px: ln.px,
      upper: !!ln.upper, lower: t?.case === 'lower',
      lh: t?.box ? 1.75 : t?.marker ? 1.45 : t?.stroke ? 1.3 : 1.18,
      stroke: sw > 0 ? { color: t?.stroke?.color ?? ln.color, w: px * sw } : undefined,
      band: t?.box ? { fill: t.box.fill, radius: ln.px * 1.5 * t.box.round, padX: ln.px * 0.45 }
        : t?.marker ? { fill: t.marker.band, radius: ln.px * 0.12, padX: ln.px * 0.45 } : undefined,
      shadow: art ?? shadow,
    }
  }
  // which drawn line is the place name (above) or a second line (below);
  // a split template's time and words read as one typed line, in the words' size
  const above = o.kind === 'caption' || o.kind === 'part'
  const hasSub = !['date', 'chapters'].includes(o.kind) && lines.length > 1
  const lead = hasSub && above ? css(lines[0]) : null
  const trail = hasSub && !above ? css(lines[lines.length - 1]) : null
  const main = css(lines[hasSub && above ? lines.length - 1 : 0])
  const backing = !tpl && (style.backing === 'box' || o.kind === 'name') && style.backing !== 'none' ? 'rgba(10,10,12,0.55)' : null
  // the quiet caption is drawn from its left edge unless it was placed by hand
  const align = o.kind === 'caption' && !o.place && !style.template && style.captions !== 'center' ? 'left' : 'center'
  return { lead, main, trail, backing, align }
}

// ---- draw -----------------------------------------------------------------

// Where each block landed on this frame, in canvas pixels (for picking and
// dragging words on the preview).
/** Where an overlay was drawn, and each line of it (the group's lines, picked one at a time). */
export type OverlayBox = { id: string; x: number; y: number; w: number; h: number; rows?: RowBox[] }
export type RowBox = { role: LineRole; x: number; y: number; w: number; h: number }

export function drawOverlays(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, W: number, H: number,
  items: Overlay[], style: OverlayStyle, parts: Part[], t: number, boxes?: OverlayBox[],
  shifts?: Record<string, number>): void {
  ctx.clearRect(0, 0, W, H)
  const u = Math.min(W, H)
  for (const o of items) {
    const motion = motionFor(o, style)
    const p = phase(o, t, motion)
    if (!p.on) continue
    if (o.kind === 'chapters') { drawChapters(ctx, W, H, u, style, parts, t, easeOut(p.pin) * p.pout); continue }
    const chars = shownChars(o, style, p.pin)
    // the quiet caption sits low and to one side; a picked template keeps the centre
    const pos = o.kind === 'caption' ? (style.captions === 'center' ? 'center' : style.template ? 'bottom' : 'bottom-left') : o.pos
    // placed by hand: centred where it was dropped, at its own size
    const a0: Anchor = o.place ? { x: o.place.x * W, align: 'center', v: 'middle', y: o.place.y * H } : anchorFor(pos, W, H)
    // moved off a face (faceShifts), the whole time it's on
    const a: Anchor = shifts?.[o.id] ? { ...a0, y: a0.y + shifts[o.id] * H } : a0
    const at = (g: number) => pose(o, p.pin, p.pout, g, u, a.align, motion)
    if (at(0).alpha <= 0.001 && at(1).alpha <= 0.001) continue
    drawBlock(ctx, W, H, u, linesFor(o, style, u * (o.place?.scale ?? 1), chars), o, style, a, at, boxes)
  }
}

// How wide a block may be: the safe width when centred, less from a side.
const fullRoom = (W: number, H: number) => { const m = safe(W, H); return W - m.l - m.r }
const roomFor = (o: Overlay, W: number, H: number) =>
  o.place || anchorFor(o.pos, W, H).align === 'center' ? fullRoom(W, H) : fullRoom(W, H) * 0.72
// A chapter title's soft shadow is only its default: where ink.py found no
// colour that reads over the frame, the halo it asked for comes first.
const haloWins = (o: Overlay) => o.kind === 'heading' && !!o.halo

// room a line needs beyond its letters: a backing's padding, 3D sides
const extra = (ln: Line) => (ln.tpl?.box || ln.tpl?.marker ? ln.px * 0.9 : 0) + (ln.tpl?.extrude ? ln.px * ln.tpl.extrude.depth : 0)

function drawBlock(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, W: number, H: number, u: number,
  lines: Line[], o: Overlay, style: OverlayStyle, a: Anchor, at: (group: number) => Pose, boxes?: OverlayBox[]) {
  const m = safe(W, H)
  const maxW = a.align === 'center' ? fullRoom(W, H) : fullRoom(W, H) * 0.72
  // measure and wrap
  type Row = { text: string; line: Line; w: number; h: number }
  const rows: Row[] = []
  for (const ln0 of lines) {
    const text = ln0.upper ? ln0.text.toUpperCase() : ln0.text
    const max = o.kind === 'caption' ? 3 : o.kind === 'title' || o.kind === 'end' ? 3 : 2
    // Words the creator wrote are never cut off: a line that won't fit
    // gets smaller first (down to 60%); only then is the end dropped.
    let ln = ln0, out: string[] = []
    if (ln0.title) {
      // a chapter title stays one line and inside the frame: smaller, never cut
      const room = maxW - extra(ln0)
      const k = fitTitle((t, px) => {
        ctx.font = lineFont(style, ln0, px)
        setTracking(ctx, ln0.track ? ln0.track * px : 0)
        return ctx.measureText(t).width
      }, text, ln0.px, room, titleFloor(o))
      ln = k === 1 ? ln0 : { ...ln0, px: ln0.px * k }
      ctx.font = lineFont(style, ln)
      setTracking(ctx, ln.track ? ln.track * ln.px : 0)
      out = ctx.measureText(text).width <= room ? [text] : wrap((t) => ctx.measureText(t).width, text, room, 2)
      const lh = ln.tpl?.stroke ? 1.3 : 1.18
      for (const r of out) rows.push({ text: r, line: ln, w: ctx.measureText(r).width + extra(ln), h: ln.px * lh })
      continue
    }
    for (let k = 1; ; k *= 0.9) {
      ln = k === 1 ? ln0 : { ...ln0, px: ln0.px * k }
      ctx.font = lineFont(style, ln)
      setTracking(ctx, ln.track ? ln.track * ln.px : 0)
      // a backing's padding comes out of the room the words have
      out = wrap((s) => ctx.measureText(s).width, text, maxW - extra(ln), max)
      if (!out[out.length - 1]?.endsWith('…') || text.endsWith('…') || k < 0.62) break
    }
    // a backing or an edge needs room around the letters, inside the block
    const lh = ln.tpl?.box ? 1.75 : ln.tpl?.marker ? 1.45 : ln.tpl?.stroke ? 1.3 : 1.18
    for (const r of out) rows.push({ text: r, line: ln, w: ctx.measureText(r).width + extra(ln), h: ln.px * lh })
  }
  if (!rows.length) return
  const gap = 0.012 * u
  const blockH = rows.reduce((n, r) => n + r.h, 0) + gap * (new Set(rows.map((r) => r.line)).size - 1)
  const blockW = Math.max(...rows.map((r) => r.w))
  const p0 = at(0)
  let y = (a.v === 'top' ? a.y : a.v === 'bottom' ? a.y - blockH : a.y - blockH / 2) + p0.dy
  const x = a.x + p0.dx
  // A scaled entrance (Hype's slam) may never push words out of the safe
  // area: the block's own room caps how big it can start.
  // Words dragged by hand go wherever they were put, up to the frame's own
  // edge (sarah, 2026-10-18: "all the way to the edge"); the safe area only
  // decides where captions sit on their own.
  const e = o.place ? { l: 0, r: 0, t: 0, b: 0 } : m
  const roomW = W - e.l - e.r, roomH = H - e.t - e.b
  const fit = Math.max(1, Math.min(roomW / Math.max(1, blockW), roomH / Math.max(1, blockH)))
  const cx = a.align === 'left' ? x + blockW / 2 : a.align === 'right' ? x - blockW / 2 : x
  const cy = y + blockH / 2
  // Scale about the block's centre, then pull it back inside the safe area
  // if the grown block would cross it on either side.
  const place = (pz: Pose) => {
    // the box a rotated block actually covers (Cozy's card tilts); a block
    // that fills the width shrinks a hair rather than tilt past the edge
    const c = Math.abs(Math.cos(pz.rot)), sn = Math.abs(Math.sin(pz.rot))
    const tilted = Math.min(roomW / (blockW * c + blockH * sn), roomH / (blockW * sn + blockH * c))
    const sc = Math.min(pz.scale, fit, pz.rot ? tilted : Infinity)
    const hw = ((blockW * c + blockH * sn) * sc) / 2, hh = ((blockW * sn + blockH * c) * sc) / 2
    const ox = Math.min(0, W - e.r - (cx + hw)) + Math.max(0, e.l - (cx - hw))
    const oy = Math.min(0, H - e.b - (cy + hh)) + Math.max(0, e.t - (cy - hh))
    return { sc, ox, oy }
  }

  ctx.save()
  const pl0 = place(p0)
  const rowBoxes: RowBox[] = []
  // a nudged line can sit outside the block: the box takes it in
  boxes?.push({ id: o.id, x: cx + pl0.ox - (blockW * pl0.sc) / 2, y: cy + pl0.oy - (blockH * pl0.sc) / 2,
                w: blockW * pl0.sc, h: blockH * pl0.sc, rows: rowBoxes })
  const toCanvas = (X: number, Y: number) => [(X - cx) * pl0.sc + cx + pl0.ox, (Y - cy) * pl0.sc + cy + pl0.oy]
  ctx.translate(cx + pl0.ox, cy + pl0.oy)
  ctx.rotate(p0.rot)
  ctx.scale(pl0.sc, pl0.sc)
  ctx.translate(-cx, -cy)
  ctx.globalAlpha = p0.alpha
  const tpl = lines[0]?.tpl
  if (tpl) {
    // a caption template brings its own edge or backing (drawn per line below)
    if (tpl.rule) {
      ctx.fillStyle = tpl.color
      ctx.fillRect(x - (a.align === 'center' ? 0.025 * u : a.align === 'right' ? 0.05 * u : 0), y - 0.014 * u, 0.05 * u, Math.max(1, 0.0015 * u))
    }
  } else if (style.backing === 'box' || o.kind === 'name') {
    const pad = 0.022 * u
    const left = a.align === 'left' ? x - pad : a.align === 'right' ? x - blockW - pad : x - blockW / 2 - pad
    ctx.fillStyle = style.backing === 'none' ? 'rgba(0,0,0,0)' : 'rgba(10,10,12,0.55)'
    roundRect(ctx, left, y - pad * 0.7, blockW + 2 * pad, blockH + pad * 1.4, pad * 0.6)
    ctx.fill()
    if (o.kind === 'name' || o.kind === 'part') {
      ctx.fillStyle = style.accent
      const bx = a.align === 'right' ? left + blockW + 2 * pad - 0.006 * u : left
      ctx.fillRect(bx, y - pad * 0.7, 0.006 * u, blockH + pad * 1.4)
    }
  } else if (o.kind === 'part') {
    // a short rule in the accent colour anchors the label without a box
    ctx.fillStyle = style.accent
    const w = 0.05 * u
    const lx = a.align === 'left' ? x : a.align === 'right' ? x - w : x - w / 2
    ctx.fillRect(lx, y + blockH + 0.014 * u, w, Math.max(2, 0.004 * u))
  }
  if (tpl && !tpl.shadow) {
    ctx.shadowColor = 'rgba(0,0,0,0)'
    ctx.shadowBlur = 0
  } else if (tpl && typeof tpl.shadow === 'object' && !haloWins(o)) {
    // set by hand: a drop down and to the right, sized from the main line
    const px = lines[lines.length - 1].px, d = tpl.shadow.dist * px * 0.7071
    ctx.shadowColor = tpl.shadow.color
    ctx.shadowBlur = tpl.shadow.blur * px
    ctx.shadowOffsetX = d
    ctx.shadowOffsetY = d
  } else if (tpl && !o.halo) {
    ctx.shadowColor = 'rgba(0,0,0,0.7)'
    ctx.shadowBlur = 0.02 * u
    ctx.shadowOffsetY = 0.003 * u
  } else if (o.halo) {
    // nothing in the palette stands out from this frame enough on its own
    ctx.shadowColor = o.halo
    ctx.shadowBlur = 0.022 * u
    ctx.shadowOffsetY = 0.002 * u
  } else if (style.backing === 'shadow') {
    ctx.shadowColor = 'rgba(0,0,0,0.6)'
    ctx.shadowBlur = 0.018 * u
    ctx.shadowOffsetY = 0.003 * u
  }
  ctx.textAlign = a.align
  ctx.textBaseline = 'top'
  let prev: Line | null = null
  let group = 0
  for (const r of rows) {
    if (prev && prev !== r.line) { y += gap; group++ }
    ctx.font = lineFont(style, r.line)
    setTracking(ctx, r.line.track ? r.line.track * r.line.px : 0)
    ctx.fillStyle = r.line.color
    // later lines fade in a stagger behind the first (the look's rhythm);
    // they move with the block, so nothing leaves the safe area mid-entrance
    ctx.globalAlpha = group ? at(group).alpha : p0.alpha
    // letter-spacing adds trailing space; shift so tracked text stays aligned
    const shift = r.line.track && a.align !== 'left' ? (r.line.track * r.line.px) / (a.align === 'center' ? 2 : 1) : 0
    const gl = r.line as Grouped
    const ddx = gl.dx ?? 0, ddy = gl.dy ?? 0
    const ty = y + ddy + (r.h - r.line.px) / 2
    if (gl.role) {
      const left = (a.align === 'left' ? x : a.align === 'right' ? x - r.w : x - r.w / 2) + ddx
      const [bx, by] = toCanvas(left, y + ddy)
      const last = rowBoxes[rowBoxes.length - 1]
      // a line that wrapped is one line to pick
      if (last && last.role === gl.role && prev === r.line) {
        const x0 = Math.min(last.x, bx), x1 = Math.max(last.x + last.w, bx + r.w * pl0.sc)
        Object.assign(last, { x: x0, w: x1 - x0, h: by + r.h * pl0.sc - last.y })
      } else rowBoxes.push({ role: gl.role, x: bx, y: by, w: r.w * pl0.sc, h: r.h * pl0.sc })
    }
    if (r.line.tpl) {
      ctx.globalAlpha = group ? at(group).alpha : p0.alpha
      const t = r.line.tpl
      if (gl.own) {
        // a line tuned on its own carries its own shadow, not the group's
        ctx.save()
        const d = typeof t.shadow === 'object' ? t.shadow.dist * r.line.px * 0.7071 : 0.003 * u
        ctx.shadowColor = !t.shadow ? 'rgba(0,0,0,0)' : typeof t.shadow === 'object' ? t.shadow.color : 'rgba(0,0,0,0.7)'
        ctx.shadowBlur = !t.shadow ? 0 : typeof t.shadow === 'object' ? t.shadow.blur * r.line.px : 0.02 * u
        ctx.shadowOffsetX = typeof t.shadow === 'object' ? d : 0
        ctx.shadowOffsetY = t.shadow ? d : 0
      }
      drawTemplateRow(ctx, r.text, r.w, r.line, t, x + shift + ddx, y + ddy, r.h, a.align)
      if (gl.own) ctx.restore()
      y += r.h
      prev = r.line
      continue
    }
    if (o.halo) {
      // a tight dark edge hugging the letters carries them over the pale
      // parts of a split frame; the soft glow set above adds the rest
      const soft = ctx.shadowBlur
      ctx.shadowBlur = 0.005 * u
      ctx.fillText(r.text, x + shift + ddx, ty)
      ctx.shadowBlur = soft
    }
    ctx.fillText(r.text, x + shift + ddx, ty)
    y += r.h
    prev = r.line
  }
  ctx.restore()
  setTracking(ctx, 0)
}

/** One line of a caption template: its backing or marker, its edge, its
 *  words (some in colour for Pop). `w` includes the backing's padding. */
function drawTemplateRow(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, text: string, w: number, ln: Line,
  tpl: Tpl, x: number, y: number, h: number, align: CanvasTextAlign) {
  const px = ln.px
  const left = align === 'left' ? x : align === 'right' ? x - w : x - w / 2
  const ty = y + (h - px) / 2
  const pad = tpl.box || tpl.marker ? px * 0.45 : 0
  if (tpl.box) {
    const bh = px * 1.5
    ctx.fillStyle = tpl.box.fill
    roundRect(ctx, left, y + (h - bh) / 2, w, bh, bh * tpl.box.round)
    ctx.fill()
  } else if (tpl.marker) {
    ctx.fillStyle = tpl.marker.band
    roundRect(ctx, left, ty - px * 0.08, w, px * 1.16, px * 0.12)
    ctx.fill()
  }
  // the words: left to right from the line's own start, so Pop can colour some
  ctx.textAlign = 'left'
  const words = tpl.pop ? text.split(/(\s+)/) : [text]
  const ranked = tpl.pop ? [...new Set(words.filter((t) => t.trim()))].sort((p, q) => q.length - p.length) : []
  const lit = new Map(ranked.slice(0, ranked.length >= 4 ? 2 : 1).map((t, i) => [t, tpl.pop![i]]))
  let cx = left + pad
  const fill = tpl.gradient ? gradientFill(ctx, tpl.gradient, ty, px) : ln.color
  ctx.lineJoin = 'round'
  for (const word of words) {
    if (!word) continue
    const paint = lit.get(word) ?? fill
    if (tpl.extrude && word.trim()) {
      // the sides first, stepping back from the face (or one hard drop)
      const steps = tpl.extrude.solid ? 1 : Math.max(2, Math.round(px * tpl.extrude.depth))
      const d = px * tpl.extrude.depth
      ctx.fillStyle = tpl.extrude.color
      ctx.strokeStyle = tpl.extrude.color
      for (let k = steps; k >= 1; k--) {
        const o = (d * k) / steps
        if (tpl.stroke) { ctx.lineWidth = px * (tpl.stroke.w + (tpl.thick ?? 0)); ctx.strokeText(word, cx + o, ty + o) }
        ctx.fillText(word, cx + o, ty + o)
      }
    }
    if (tpl.stroke && word.trim()) {
      ctx.lineWidth = px * (tpl.stroke.w + (tpl.thick ?? 0))
      ctx.strokeStyle = tpl.stroke.color
      ctx.strokeText(word, cx, ty)
    }
    if (tpl.thick && word.trim()) {
      ctx.lineWidth = px * tpl.thick
      ctx.strokeStyle = paint
      ctx.strokeText(word, cx, ty)
    }
    ctx.fillStyle = paint
    if (tpl.glow && word.trim()) {
      // neon: the light, twice for depth, then the letters crisp on top
      ctx.save()
      ctx.shadowColor = tpl.glow.color
      ctx.shadowOffsetX = 0
      ctx.shadowOffsetY = 0
      ctx.shadowBlur = px * tpl.glow.blur
      ctx.fillText(word, cx, ty)
      ctx.shadowBlur = px * tpl.glow.blur * 0.4
      ctx.fillText(word, cx, ty)
      ctx.restore()
    }
    ctx.fillText(word, cx, ty)
    cx += ctx.measureText(word).width
  }
  ctx.textAlign = align
}

function gradientFill(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, [a, b]: [string, string], ty: number, px: number) {
  if (!ctx.createLinearGradient) return a
  const g = ctx.createLinearGradient(0, ty, 0, ty + px)
  g.addColorStop(0.15, a)
  g.addColorStop(0.9, b)
  return g
}

function drawChapters(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, W: number, H: number, u: number,
  style: OverlayStyle, parts: Part[], t: number, alpha: number) {
  if (parts.length < 2 || alpha <= 0.001) return
  const m = safe(W, H)
  const total = parts[parts.length - 1].end - parts[0].start
  const x0 = m.l
  const width = W - m.l - m.r
  const y = m.t * 0.55
  const gap = 0.008 * u
  const h = Math.max(3, 0.007 * u)
  const cur = partAt(parts, t)
  ctx.save()
  ctx.globalAlpha = alpha
  let x = x0
  const room = width - gap * (parts.length - 1)
  parts.forEach((p, i) => {
    const w = room * ((p.end - p.start) / total)
    ctx.fillStyle = i === cur ? style.accent : i < cur ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.28)'
    roundRect(ctx, x, y, w, h, h / 2)
    ctx.fill()
    if (i === cur) {
      ctx.font = fontCss(style, 0.024 * u, true)
      ctx.fillStyle = style.color
      ctx.textBaseline = 'top'
      ctx.textAlign = 'left'
      ctx.shadowColor = 'rgba(0,0,0,0.6)'
      ctx.shadowBlur = 0.012 * u
      const label = p.title.length > 40 ? p.title.slice(0, 39) + '…' : p.title
      const tw = ctx.measureText(label).width
      ctx.fillText(label, Math.min(Math.max(x, x0), x0 + width - tw), y + h + 0.012 * u)
      ctx.shadowBlur = 0
    }
    x += w + gap
  })
  ctx.restore()
}

function roundRect(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
}

function setTracking(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, px: number) {
  if ('letterSpacing' in ctx) (ctx as { letterSpacing: string }).letterSpacing = `${px}px`
}

// ---- export ---------------------------------------------------------------

export type ScheduleEntry = { frame: number | null; start: number; end: number }

/** A layer drawn under the words in the same frames (the graphic
 *  animations, graphicDraw.ts): which frames it's on, a key that changes
 *  when its pixels do, and how to draw it at t onto a cleared canvas. */
export type UnderLayer = { frames: number[]; key: (t: number) => string; draw: (ctx: OffscreenCanvasRenderingContext2D, t: number) => void }
// ---- off faces -----------------------------------------------------------

/** Where faces sit in an export's frame, shot by shot (backend
 *  export.face_areas): shares of the frame, top-left origin. */
export type FaceArea = { start: number; end: number; boxes: [number, number, number, number][] }

// room kept between words and a face, a share of the short side [prior]
const FACE_MARGIN = 0.02
// how finely a caption is slid up or down looking for a clear spot
const SLIDE_STEP = 0.01

/** In a version laid out again for another frame (a vertical version of a
 *  wide edit), a caption can land on the person the crop just centred --
 *  a caption over a face is the plainest tell there is. For each caption,
 *  the faces on screen at any moment it's shown; if its block covers one,
 *  it slides up or down (never sideways: its alignment is the look's) to
 *  the nearest place that covers none, else the one that covers least.
 *  One shift per caption for its whole time on screen, so words never jump
 *  at a cut. Returns {overlay id: shift as a share of the height}. */
export function faceShifts(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, W: number, H: number,
  items: Overlay[], style: OverlayStyle, parts: Part[], faces: FaceArea[]): Record<string, number> {
  const out: Record<string, number> = {}
  if (!faces.length) return out
  const u = Math.min(W, H), pad = FACE_MARGIN * u, m = safe(W, H)
  for (const o of items) {
    if (o.kind === 'chapters') continue
    const rects = faces.filter((f) => f.start < o.shown_end && f.end > o.start)
      .flatMap((f) => f.boxes.map(([x, y, w, h]) => ({ l: x * W - pad, t: y * H - pad, r: (x + w) * W + pad, b: (y + h) * H + pad })))
    if (!rects.length) continue
    // the block as it sits once fully in (its entrance done)
    const { inS, outS } = envelope(o, motionFor(o, style))
    const t = Math.min(o.start + inS + 0.05, Math.max(o.start, o.shown_end - outS - 0.05))
    const boxes: OverlayBox[] = []
    drawOverlays(ctx, W, H, [o], style, parts, t, boxes)
    const bx = boxes.find((b) => b.id === o.id)
    if (!bx) continue
    const cover = (dy: number) => rects.reduce((n, r) =>
      n + Math.max(0, Math.min(bx.x + bx.w, r.r) - Math.max(bx.x, r.l)) * Math.max(0, Math.min(bx.y + dy + bx.h, r.b) - Math.max(bx.y + dy, r.t)), 0)
    const now = cover(0)
    if (now <= 0) continue
    // within the frame's safe area (or the frame, for words placed by hand)
    const top = (o.place ? 0 : m.t) - bx.y, bottom = H - (o.place ? 0 : m.b) - (bx.y + bx.h)
    let best = 0, bestCover = now
    const step = SLIDE_STEP * H
    for (let dy = Math.ceil(top / step) * step; dy <= bottom; dy += step) {
      const c = cover(dy)
      if (c < bestCover - 1e-6 || (Math.abs(c - bestCover) <= 1e-6 && Math.abs(dy) < Math.abs(best))) { best = dy; bestCover = c }
    }
    if (best) out[o.id] = best / H
  }
  ctx.clearRect(0, 0, W, H)
  return out
}

/** Render every distinct overlay frame of the edit, hand each PNG to
 *  `upload`, and return when each frame is on screen. Equal keys -> one
 *  frame; frames nothing is on are left out (transparent). */
export async function renderSchedule(opts: {
  items: Overlay[]; style: OverlayStyle; parts: Part[]; fps: number; total: number; w: number; h: number
  under?: UnderLayer
  // faces in this frame (a version in the other frame): captions are moved off them
  faces?: FaceArea[]
  onMoved?: (n: number) => void
  upload: (n: number, png: Blob) => Promise<void>
  onProgress?: (done: number, of: number) => void
  cancelled?: () => boolean
}): Promise<ScheduleEntry[]> {
  const { items, style, parts, fps, total, w, h, under } = opts
  await ensureFonts(style)
  const frames = under ? [...new Set([...busyFrames(items, fps, total), ...under.frames])].sort((a, b) => a - b) : busyFrames(items, fps, total)
  const canvas = new OffscreenCanvas(w, h)
  const ctx = canvas.getContext('2d')!
  const below = under ? new OffscreenCanvas(w, h) : null
  const shifts = opts.faces?.length ? faceShifts(ctx, w, h, items, style, parts, opts.faces) : {}
  opts.onMoved?.(Object.keys(shifts).length)
  const schedule: ScheduleEntry[] = []
  const seen = new Map<string, number>()
  const pending = new Set<Promise<void>>()
  let n = 0
  let prevF = -2
  let prevKey = ''
  for (let i = 0; i < frames.length; i++) {
    if (opts.cancelled?.()) throw new Error('cancelled')
    const f = frames[i]
    const t = f / fps
    const words = frameKey(items, parts, t, style.motion, style)
    const art = under ? under.key(t) : ''
    const key = art ? `${words}#${art}` : words
    if (!key) { prevF = f; prevKey = ''; continue }
    if (key === prevKey && f === prevF + 1) {
      schedule[schedule.length - 1].end = (f + 1) / fps
    } else {
      let id = seen.get(key)
      if (id == null) {
        id = n++
        seen.set(key, id)
        drawOverlays(ctx, w, h, items, style, parts, t, undefined, shifts)
        if (below && art) {
          // the layer goes under the words: drawn on its own, then slid beneath
          const bctx = below.getContext('2d')!
          bctx.clearRect(0, 0, w, h)
          under!.draw(bctx, t)
          ctx.globalCompositeOperation = 'destination-over'
          ctx.drawImage(below, 0, 0)
          ctx.globalCompositeOperation = 'source-over'
        }
        const blob = await canvas.convertToBlob({ type: 'image/png' })
        const p: Promise<void> = opts.upload(id, blob).finally(() => pending.delete(p))
        pending.add(p)
        if (pending.size >= 4) await Promise.race(pending)
      }
      schedule.push({ frame: id, start: f / fps, end: (f + 1) / fps })
    }
    prevF = f
    prevKey = key
    if (i % 10 === 0) opts.onProgress?.(i, frames.length)
  }
  await Promise.all(pending)
  opts.onProgress?.(frames.length, frames.length)
  return schedule
}

/** The parts of the edit in sequence time, from the timeline's items. */
export function partsOf(items: { beat_id: string; beat_title: string; seq_start: number; seq_end: number }[]): Part[] {
  const out: Part[] = []
  for (const it of items) {
    const last = out[out.length - 1]
    if (last && last.id === it.beat_id) last.end = it.seq_end
    else out.push({ id: it.beat_id, title: it.beat_title, start: it.seq_start, end: it.seq_end })
  }
  return out
}
