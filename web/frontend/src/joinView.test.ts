import assert from 'node:assert/strict'
import { test } from 'node:test'
import { byKey, dissolveAfter, mixAt, preloadAt, swipeAt, veilAt } from './joinView.ts'
import type { SeqItem } from './sequence'

const it = (key: string, s0: number, s1: number, q0: number, extra: Partial<SeqItem> = {}): SeqItem => ({
  key, kind: 'shot', shot_id: key, clip_id: key.split(':')[0], src_start: s0, src_end: s1,
  seq_start: q0, seq_end: q0 + (s1 - s0), beat_id: 'b', beat_title: 'B', n: 1, ...extra,
})
const FPS = 30
// a (2 s) dissolving into b (3 s) over 10 + 10 frames; b fades out to black over 15 frames
const items = [it('a:0', 1, 3, 0), it('b:0', 4, 7, 2)]
const tr = byKey([
  { key: 'a:0', head: 0, tail: 10, fade_in: [30, 'black'], fade_out: null },
  { key: 'b:0', head: 10, tail: 0, fade_in: null, fade_out: [15, 'black'] },
])

test('a dissolve window straddles the cut exactly as the export overlaps it', () => {
  const d = dissolveAfter(items, 0, tr, FPS)!
  assert.ok(Math.abs(d.from - (2 - 10 / 30)) < 1e-9 && Math.abs(d.to - (2 + 10 / 30)) < 1e-9 && d.cut === 2)
  assert.ok(Math.abs(d.inFrom - (4 - 10 / 30)) < 1e-9, 'the incoming shot starts its handle early')
  assert.equal(mixAt(d, d.from), 0)
  assert.ok(Math.abs(mixAt(d, d.cut) - 0.5) < 1e-9)   // equal handles: half and half on the cut frame
  assert.equal(mixAt(d, d.to), 1)
})

test('a plain cut has no dissolve, and the next shot waits at its first frame', () => {
  const plain = byKey([])
  assert.equal(dissolveAfter(items, 0, plain, FPS), null)
  assert.deepEqual(preloadAt(items, 0, plain, FPS), { clip: 'b', url: '/api/video/b', t: 4 })
  assert.ok(Math.abs(preloadAt(items, 0, tr, FPS)!.t - (4 - 10 / 30)) < 1e-9)
})

test('the veil fades from the colour at the open and to it at the close', () => {
  assert.deepEqual(veilAt(items, 0, tr, 0, FPS), { color: 'black', alpha: 1 })
  assert.equal(veilAt(items, 0, tr, 0.5, FPS)!.alpha, 0.5)
  assert.equal(veilAt(items, 0, tr, 1.2, FPS), null)
  const end = items[1].seq_end
  assert.equal(veilAt(items, 1, tr, end - 0.25, FPS)!.alpha, 0.5)
  assert.ok(veilAt(items, 1, tr, end - 1e-6, FPS)!.alpha > 0.99)
})

test('nothing next to a gap dissolves, and a gap preloads nothing', () => {
  const g = [it('a:0', 1, 3, 0), { ...it('gap', 0, 1, 2), kind: 'gap' as const, clip_id: null }]
  assert.equal(dissolveAfter(g, 0, tr, FPS), null)
  assert.equal(preloadAt(g, 0, tr, FPS), null)
})

test('a swipe uses the dissolve window but slides: out to the left, in from the right', () => {
  const sw = byKey([
    { key: 'a:0', head: 0, tail: 5, fade_in: null, fade_out: null, swipe: true },
    { key: 'b:0', head: 5, tail: 0, fade_in: null, fade_out: null },
  ])
  const d = dissolveAfter(items, 0, sw, FPS)!
  assert.equal(d.swipe, true)
  assert.deepEqual(swipeAt(d, d.from), { outX: -0, inX: 1, smear: false })
  const mid = swipeAt(d, d.cut)
  assert.ok(Math.abs(mid.outX + 0.5) < 1e-9 && Math.abs(mid.inX - 0.5) < 1e-9 && mid.smear)
  assert.deepEqual(swipeAt(d, d.to), { outX: -1, inX: 0, smear: false })
  assert.equal(dissolveAfter(items, 0, tr, FPS)!.swipe, false, 'a dissolve stays a dissolve')
})
