import assert from 'node:assert/strict'
import { test } from 'node:test'
import { compact, dwell, panelOf, showFit, showLength, viewOf, type MakeShow, type ShowKind, type ShowStep } from './makeShow.ts'
import type { Session } from './types'

const item = (key: string, a: number, b: number) => ({ key, kind: 'shot', seq_start: a, seq_end: b })
const view = (items: ReturnType<typeof item>[], music: unknown = null) =>
  ({ board: { beats: [] }, timeline: { items, total: items.length ? items[items.length - 1].seq_end : 0 }, overlays: {}, graphics: {},
     music, mix: null, seams: [], last: null }) as unknown as MakeShow['views'][number]

function steps(lay: number, trim: number, words: number): ShowStep[] {
  const k = (kind: ShowKind): ShowStep => ({ kind, say: kind, view: 0, at: 0 })
  return [k('read'), ...Array.from({ length: lay }, () => k('lay')), ...Array.from({ length: trim }, () => k('trim')),
    k('hook'), k('order'), k('teaser'), k('music'), k('frame'), k('look'), ...Array.from({ length: words }, () => k('words')), k('push'), k('turn')]
}

test('the show is about 20 to 30 seconds, whatever the size of the shoot', () => {
  for (const [lay, trim, words] of [[3, 1, 2], [26, 7, 7], [60, 7, 8], [200, 12, 20]]) {
    const ms = showLength(compact(steps(lay, trim, words)))
    assert.ok(ms >= 17000 && ms <= 32000, `${lay} clips, ${trim} parts, ${words} lines: ${ms} ms`)
  }
})

test('clips land quickly and share one budget; a big shoot lands faster, never a blur', () => {
  const few = steps(3, 1, 0), many = steps(120, 7, 0)
  assert.ok(dwell(few[1], few) > dwell(many[1], many))
  assert.ok(dwell(many[1], many) >= 140)
  const s = steps(26, 7, 2)
  assert.ok(Math.abs(s.filter((x) => x.kind === 'lay').reduce((t, x) => t + dwell(x, s), 0) - 5000) < 200)
})

test('each move opens the panel it uses and lights it', () => {
  assert.deepEqual(panelOf('lay'), { side: 'media', tab: 'edit', lit: ['side', 'timeline'] })
  assert.equal(panelOf('music').side, 'music')
  assert.equal(panelOf('music').tab, 'audio')
  assert.equal(panelOf('look').tab, 'adjust')
  assert.equal(panelOf('words').tab, 'captions')
  assert.equal(panelOf('words').side, 'text')
  assert.equal(panelOf('joins').tab, 'effects')
  assert.equal(panelOf('trim').side, null)           // the trim keeps whatever is open on the left
})

test('a board being laid shows only its first shots; the rest of the session is the finished one', () => {
  const real = { turns: [{ id: 7 }], brief: { message: 'hi' }, timeline: { items: [], total: 0 } } as unknown as Session
  const laid = view([item('a', 0, 4), item('b', 4, 9), item('c', 9, 15)])
  const show: MakeShow = { steps: [{ kind: 'lay', say: '', view: 0, at: 0, reveal: 2 }, { kind: 'trim', say: '', view: 1, at: 0 }],
    views: [laid, view([item('a', 0, 2), item('b', 2, 3.5)], { title: 'beat' })] }
  const v = viewOf(real, show, 0)
  assert.deepEqual(v.timeline.items.map((x) => x.key), ['a', 'b'])
  assert.equal(v.timeline.total, 9)
  assert.equal(v.turns, real.turns)          // the log is the finished edit's: Undo, History and the chat don't move
  assert.equal(v.brief, real.brief)
  assert.equal(viewOf(real, show, 1).timeline.total, 3.5)
  assert.deepEqual(showFit(show), { total: 15, count: 3 })
})

test('a long edit plays its moves in handfuls, ending on the last of each', () => {
  const s = steps(200, 12, 20).map((x, i) => ({ ...x, view: i }))
  const c = compact(s)
  const lays = c.filter((x) => x.kind === 'lay')
  assert.ok(lays.length <= 36 && lays.length >= 30, String(lays.length))
  assert.equal(lays[lays.length - 1].view, s.filter((x) => x.kind === 'lay').pop()!.view)   // the last clip still lands
  assert.equal(c.filter((x) => x.kind === 'words').pop()!.view, s.filter((x) => x.kind === 'words').pop()!.view)
  assert.equal(c[c.length - 1], s[s.length - 1])
  assert.deepEqual(compact(steps(3, 1, 2)), steps(3, 1, 2))   // a small one plays every move
})
