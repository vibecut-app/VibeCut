import assert from 'node:assert/strict'
import { test } from 'node:test'
import { beatAt, clock, fromMedia, locate, mediaEnd, mediaUrl, parseTimecode, readout, smpte, toMedia, toSource, type SeqItem } from './sequence.ts'

test('typed timecodes: seconds, m:ss, h:mm:ss and SMPTE frames', () => {
  assert.equal(parseTimecode('21.3', 30), 21.3)
  assert.equal(parseTimecode('0:21.3', 30), 21.3)
  assert.equal(parseTimecode('1:02:03.5', 30), 3723.5)
  assert.ok(Math.abs(parseTimecode('00:00:21:09', 30)! - 21.3) < 1e-9)
  assert.equal(parseTimecode('21', 30), 21)
  for (const bad of ['', 'abc', '1:75', '00:00:21:40', '-3', '1::2', '0:21.3.4']) {
    assert.equal(parseTimecode(bad, 30), null, bad)
  }
})

test('clock and SMPTE formatting round-trip', () => {
  assert.equal(clock(21.3), '0:21.30')
  assert.equal(clock(3723.5), '1:02:03.50')
  assert.equal(smpte(21.3, 30), '00:00:21:09')
  assert.ok(Math.abs(parseTimecode(smpte(83.4, 30), 30)! - 83.4) < 1 / 30)
})

const item = (n: number, a: number, b: number): SeqItem => ({
  key: `k${n}`, kind: 'shot', shot_id: `s${n}`, clip_id: 'c', src_start: 100, src_end: 100 + b - a,
  seq_start: a, seq_end: b, beat_id: 't1', beat_title: 'x', n,
})
const items = [item(1, 0, 10), item(2, 10, 19.2), item(3, 19.2, 30)]

test('locate finds the item under the playhead by binary search', () => {
  assert.equal(locate(items, 0), 0)
  assert.equal(locate(items, 9.999), 0)
  assert.equal(locate(items, 10), 1)
  assert.equal(locate(items, 30), 2)
})

test('readout says what is at the playhead', () => {
  assert.equal(readout(items, null, 21.3), 'Shot 3 · 2.1s in · 0:21.30')
  assert.equal(readout(items, { bpm: 120, phase: 0 }, 21.3), 'Shot 3 · 2.1s in · 0:21.30 · beat 3 of 4')
  assert.deepEqual(beatAt({ bpm: 120, phase: 0.25 }, 0.1), null)
})

test('a reversed shot: the file is its span backwards, tools still get source time', () => {
  // 4 s of source (101–105) at 2x: 2 s in the edit, starting at 10
  const r: SeqItem = { ...item(9, 10, 12), src_start: 101, src_end: 105, speed: 2, reverse: true }
  assert.equal(mediaUrl(r), '/api/reversed/c?a=101&b=105')
  assert.equal(toSource(r, 10), 105)      // plays its last source frame first
  assert.equal(toSource(r, 11.5), 102)
  assert.equal(toMedia(r, 11.5), 3)       // 3 s into the reversed file
  assert.equal(fromMedia(r, 3), 11.5)
  assert.equal(mediaEnd(r), 4)
})

test('a held frame shows its one frame the whole time', () => {
  const f: SeqItem = { ...item(8, 5, 8), src_start: 42, src_end: 45, freeze: true }
  assert.equal(mediaUrl(f), '/api/video/c')
  assert.equal(toMedia(f, 5), 42)
  assert.equal(toMedia(f, 7.9), 42)
  assert.equal(toSource(f, 6.5), 43.5)    // a cut at the playhead still splits its length
})

test('a steadied shot: the file is its span with 1.5 s either side, tools still get source time', () => {
  const s: SeqItem = { ...item(9, 10, 14), src_start: 101, src_end: 105, stabilize: 0.6 }
  assert.equal(mediaUrl(s), '/api/steady/c?a=101&b=105&s=0.6')
  assert.equal(toSource(s, 11), 102)
  assert.equal(toMedia(s, 10), 1.5)        // the span starts 1.5 s into the steady file
  assert.equal(fromMedia(s, 3.5), 12)
  assert.equal(mediaEnd(s), 5.5)
  // filmed from the clip's first second: the file starts at 0
  const early: SeqItem = { ...s, src_start: 0.5, src_end: 3 }
  assert.equal(toMedia(early, 10), 0.5)
  // backwards too: the steady span reversed, mapped as a reversed shot
  const back: SeqItem = { ...s, reverse: true }
  assert.equal(mediaUrl(back), '/api/steady/c?a=101&b=105&s=0.6&rev=1')
  assert.equal(toMedia(back, 11), 1)
  assert.equal(mediaEnd(back), 4)
})
