// A shot's own Brightness, Contrast and Saturation as the preview draws
// them: the browser's own filters, whose numbers export copies exactly
// (backend tone.py; tests/test_adjust.py checks ffmpeg against the same sums).

export type Tone = { brightness?: number; contrast?: number; saturation?: number }
export const TONES: [keyof Tone, string][] = [['brightness', 'Brightness'], ['contrast', 'Contrast'], ['saturation', 'Saturation']]

// [priors] -- the same as tone.py: what the slider's ends do
export const BRIGHT = 0.4, CONTRAST = 0.5, SATURATE = 1

const r4 = (x: number) => String(Math.round(x * 10000) / 10000)

/** CSS for the shot's adjustment, '' when it is as filmed. */
export function toneFilter(t: Tone | null | undefined): string {
  if (!t) return ''
  const out: string[] = []
  if (t.brightness) out.push(`brightness(${r4(1 + BRIGHT * t.brightness)})`)
  if (t.contrast) out.push(`contrast(${r4(1 + CONTRAST * t.contrast)})`)
  if (t.saturation) out.push(`saturate(${r4(1 + SATURATE * t.saturation)})`)
  return out.join(' ')
}

/** What that does to one 0..255 colour, step by step as the browser does. */
export function toneApply(rgb: [number, number, number], t: Tone): [number, number, number] {
  const k = 1 + BRIGHT * (t.brightness ?? 0), c = 1 + CONTRAST * (t.contrast ?? 0), s = 1 + SATURATE * (t.saturation ?? 0)
  const clip = (x: number) => Math.max(0, Math.min(255, x))
  const [r, g, b] = rgb.map((x) => clip((clip(x * k) - 127.5) * c + 127.5))
  return [
    clip((0.213 + 0.787 * s) * r + (0.715 - 0.715 * s) * g + (0.072 - 0.072 * s) * b),
    clip((0.213 - 0.213 * s) * r + (0.715 + 0.285 * s) * g + (0.072 - 0.072 * s) * b),
    clip((0.213 - 0.213 * s) * r + (0.715 - 0.715 * s) * g + (0.072 + 0.928 * s) * b),
  ]
}

/** The shot's tone as one record (only what's set), for comparing shots. */
export const toneOf = (t: Tone): Required<Tone> =>
  ({ brightness: t.brightness ?? 0, contrast: t.contrast ?? 0, saturation: t.saturation ?? 0 })
