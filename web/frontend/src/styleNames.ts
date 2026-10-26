import { useEffect, useState } from 'react'
import type { CaptionEnter, CaptionTemplate } from './types'

// What the caption styles, entrances and transitions are called, and the
// loop their tiles play on: shared by the editor's tabs (StyleBars.tsx) and
// the profile's questions (ProfileAsk.tsx).

export const TEMPLATE_NAMES: Record<CaptionTemplate, string> = {
  outlined: 'Outlined', bold: 'Big & bold', label: 'Label', highlight: 'Highlighter',
  handwritten: 'Handwritten', tape: 'Typed tape', pop: 'Pop colour', quiet: 'Quiet',
  neon: 'Neon', glow: 'Glow', gradient: 'Gradient', extrude: '3D', retro: 'Retro drop',
}
export const ENTER_NAMES: Record<CaptionEnter, string> = {
  fade: 'Fade up', pop: 'Pop', slide: 'Slide in', stamp: 'Stamp', type: 'Typewriter', word: 'Word by word',
}
export const TRANSITION_NAMES: Record<string, string> = {
  cut: 'Cut', dissolve: 'Fade', dip_black: 'Dip to black', flash: 'Flash',
  zoom: 'Zoom through', slide_up: 'Slide up', blur: 'Blur', light_leak: 'Light leak', swipe: 'Swipe',
}

/** 0..1, round and round every `period` seconds while mounted. */
export function useLoop(period: number): number {
  const [m, setM] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const tick = (now: number) => { setM(((now - t0) / 1000 / period) % 1); raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [period])
  return m
}
