import type { Session } from './types'
import type { InspectorTab } from './components/Inspector'

// Watch it edit (sarah, 2026-11-24: "instead of making it generating
// immediate, can you show the specific moves youre doing"). After Make lands,
// the editor plays back how the edit was put together, one move at a time,
// on its own timeline, panels and preview, then opens the finished video as
// before. Each step's board comes from the backend (show.py): the clips laid
// whole in the order they were filmed, each part trimmed, the best moment
// moved to the front, the song and its beat, the frame, the look, the words,
// the push-ins. It is a playback of moves already decided: the edit had
// landed before the first step, nothing can be changed while it plays, and
// Skip (or Escape) goes straight to the result.

export type ShowKind = 'read' | 'lay' | 'trim' | 'hook' | 'order' | 'teaser' | 'music' | 'frame' | 'look'
  | 'words' | 'push' | 'speed' | 'joins' | 'graphics' | 'other' | 'turn'

/** The parts of a session one step changes (backend app._view_of). */
export type ShowView = Pick<Session, 'board' | 'timeline' | 'overlays' | 'graphics' | 'music' | 'mix' | 'seams' | 'last'>

export type ShowStep = {
  kind: ShowKind
  /** the one line it says while the step is on screen */
  say: string
  view: number
  /** where the playhead goes, edit seconds */
  at: number
  /** a board being laid: only its first n shots are down yet */
  reveal?: number
  shot?: string | null
  overlay?: string
  join?: string | null
}

export type MakeShow = { steps: ShowStep[]; views: ShowView[] }

// How long a move stays on screen [priors: the whole show near 25 s, the
// promise was "about 20 to 30 seconds"]. The clips landing share LAY_MS, the
// parts being trimmed TRIM_MS and the lines being typed WORDS_MS, so a big
// shoot isn't a longer show, only quicker hands.
export const LAY_MS = 5000
export const TRIM_MS = 4000
export const WORDS_MS = 6000
const SHARED: Partial<Record<ShowKind, [number, number, number]>> = {
  lay: [LAY_MS, 140, 450], trim: [TRIM_MS, 450, 1000], words: [WORDS_MS, 800, 1400],
}
const HOLD_MS: Partial<Record<ShowKind, number>> = { read: 1400, music: 1800, look: 1500 }
const STEP_MS = 1200

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x))

export function dwell(step: ShowStep, steps: ShowStep[]): number {
  const share = SHARED[step.kind]
  if (share) return Math.round(clamp(share[0] / steps.filter((s) => s.kind === step.kind).length, share[1], share[2]))
  return HOLD_MS[step.kind] ?? STEP_MS
}

// Beyond this many of one kind, every few are played together [prior]: a
// long edit's 200 shots land in about 36 handfuls, not one by one in a blur.
// Each step's board holds everything before it, so a step left out only
// means its change arrives with the next one.
const MOST: Partial<Record<ShowKind, number>> = { lay: 36, trim: 10, words: 8 }

export function compact(steps: ShowStep[]): ShowStep[] {
  const drop = new Set<number>()
  for (const [kind, most] of Object.entries(MOST) as [ShowKind, number][]) {
    const at = steps.flatMap((s, i) => (s.kind === kind ? [i] : []))
    if (at.length <= most) continue
    const every = Math.ceil(at.length / most)
    at.forEach((i, n) => { if ((n + 1) % every !== 0 && n !== at.length - 1) drop.add(i) })
  }
  return steps.filter((_, i) => !drop.has(i))
}

export function showLength(steps: ShowStep[]): number {
  return steps.reduce((t, s) => t + dwell(s, steps), 0)
}

export type Lit = 'side' | 'inspector' | 'timeline' | 'preview'
export type Panels = { side: 'media' | 'text' | 'music' | null; tab: InspectorTab; lit: Lit[] }

/** Where each move happens: the panel it opens on the left (null: leave it), the inspector's tab, and what lights up. */
export function panelOf(kind: ShowKind): Panels {
  switch (kind) {
    case 'read': return { side: 'media', tab: 'edit', lit: ['side'] }
    case 'lay': return { side: 'media', tab: 'edit', lit: ['side', 'timeline'] }
    case 'trim': case 'hook': case 'order': case 'teaser': return { side: null, tab: 'edit', lit: ['timeline', 'inspector'] }
    case 'music': return { side: 'music', tab: 'audio', lit: ['side', 'timeline'] }
    case 'look': return { side: null, tab: 'adjust', lit: ['preview', 'inspector'] }
    case 'words': return { side: 'text', tab: 'captions', lit: ['preview', 'side'] }
    case 'joins': return { side: null, tab: 'effects', lit: ['timeline', 'inspector'] }
    case 'graphics': return { side: null, tab: 'graphics', lit: ['preview', 'inspector'] }
    default: return { side: null, tab: 'edit', lit: ['preview', 'inspector'] }
  }
}

/** The session as step k shows it: the finished one, with that step's board,
 *  timeline, words and music; a board being laid shows only its first shots. */
export function viewOf(real: Session, show: MakeShow, k: number): Session {
  const s = show.steps[k]
  const v = show.views[s.view]
  let timeline = v.timeline
  if (s.reveal != null) {
    const items = timeline.items.slice(0, s.reveal)
    timeline = { ...timeline, items, total: items.length ? items[items.length - 1].seq_end : 0 }
  }
  return { ...real, ...v, timeline }
}

/** The timeline's one scale for the whole show: the longest the edit gets while it's put together. */
export function showFit(show: MakeShow): { total: number; count: number } {
  return {
    total: Math.max(0, ...show.views.map((v) => v.timeline.total)),
    count: Math.max(0, ...show.views.map((v) => v.timeline.items.length)),
  }
}
