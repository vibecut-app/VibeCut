import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseRoute, routeHash } from './router.ts'

test('routes parse and print both ways', () => {
  for (const h of ['#/', '#/profile', '#/polish', '#/welcome', '#/p/0123456789ab', '#/p/0123456789ab/frames']) {
    assert.equal(routeHash(parseRoute(h)), h)
  }
})

test('old and odd links land somewhere sensible', () => {
  assert.deepEqual(parseRoute(''), { kind: 'projects' })
  assert.deepEqual(parseRoute('#profile'), { kind: 'profile' })
  assert.deepEqual(parseRoute('#polish'), { kind: 'polish' })
  assert.deepEqual(parseRoute('#tools'), { kind: 'projects' })
  assert.deepEqual(parseRoute('#/welcome#pricing'), { kind: 'landing' })
  assert.deepEqual(parseRoute('#/p/nope'), { kind: 'projects' })
  assert.deepEqual(parseRoute('#/p/0123456789ab/story/'), { kind: 'project', id: '0123456789ab', view: 'story' })
})
