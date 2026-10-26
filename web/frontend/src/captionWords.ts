import type { Overlay } from './types.ts'

// A caption's words as one block of text, the lines as they read on the
// picture (sarah, 2026-10-18: CapCut and the rest keep a caption's words in
// one box). A caption's place name and a part's label sit above the main
// line, a title's or name tag's second line below; a date has one line, and
// a chapter list isn't typed into at all.
type Words = Pick<Overlay, 'kind' | 'text' | 'sub'>

export const typable = (o: Words) => o.kind !== 'chapters'
export const multiline = (o: Words) => !['date', 'chapters'].includes(o.kind)
const above = (o: Words) => o.kind === 'caption' || o.kind === 'part'

export function wordsOf(o: Words): string {
  return !o.sub ? o.text : above(o) ? `${o.sub}\n${o.text}` : `${o.text}\n${o.sub}`
}

// The caption as it stands while its words are being typed, so the box can
// size itself on what's typed rather than what was saved.
export function asTyped<T extends Words>(o: T, v: string): T {
  return { ...o, ...(wordsPatch(o, v) ?? {}) }
}

// What changed, as an edit_overlay patch; null when nothing did or the box
// was emptied (deleting is its own button, not an empty box).
export function wordsPatch(o: Words, v: string): { text?: string; sub?: string } | null {
  const ls = v.split('\n').map((x) => x.trim()).filter(Boolean)
  if (!ls.length) return null
  const two = multiline(o)
  const [text, sub] = !two || ls.length === 1 ? [ls.join(' '), ''] : above(o)
    ? [ls.slice(1).join(' '), ls[0]] : [ls[0], ls.slice(1).join(' ')]
  const patch: { text?: string; sub?: string } = {}
  if (text !== o.text) patch.text = text
  if (two && sub !== o.sub) patch.sub = sub
  return Object.keys(patch).length ? patch : null
}
