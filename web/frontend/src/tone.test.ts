import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { BRIGHT, CONTRAST, SATURATE, toneApply, toneFilter } from './tone.ts'

// The preview's Brightness / Contrast / Saturation are the export's
// (backend tone.py; tests/test_adjust.py renders them through ffmpeg).

test('as filmed: no filter at all', () => {
  assert.equal(toneFilter(null), '')
  assert.equal(toneFilter({ brightness: 0, contrast: 0, saturation: 0 }), '')
})

test('each slider is one CSS filter, in the export\'s order', () => {
  assert.equal(toneFilter({ brightness: 0.5 }), 'brightness(1.2)')
  assert.equal(toneFilter({ saturation: -1 }), 'saturate(0)')
  assert.equal(toneFilter({ saturation: 0.8, brightness: -0.4, contrast: -0.5 }), 'brightness(0.84) contrast(0.75) saturate(1.8)')
})

test('the same numbers as tone.py', () => {
  const py = readFileSync(new URL('../../backend/tone.py', import.meta.url), 'utf8')
  const num = (name: string) => Number(new RegExp(`^${name} = ([\\d.]+)`, 'm').exec(py)![1])
  assert.equal(BRIGHT, num('BRIGHT'))
  assert.equal(CONTRAST, num('CONTRAST'))
  assert.equal(SATURATE, num('SATURATE'))
})

test('the sums move the picture the way the sliders say', () => {
  // the values tests/test_adjust.py got out of ffmpeg for the same colours
  const near = (a: number[], b: number[]) => a.every((x, i) => Math.abs(x - b[i]) <= 1)
  assert.ok(near(toneApply([40, 90, 200], { brightness: 0.5 }), [48, 108, 240]))
  assert.ok(near(toneApply([40, 90, 200], { saturation: -1 }), [87, 87, 87]))
  assert.ok(near(toneApply([200, 120, 60], { contrast: 0.6 }), [221, 117, 39]))
  const grey = toneApply([128, 128, 128], { saturation: 1 })
  assert.ok(near(grey, [128, 128, 128]), 'grey has no colour to add')
})
