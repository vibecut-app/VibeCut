import assert from 'node:assert/strict'
import { test } from 'node:test'
import { asTyped, wordsOf, wordsPatch } from './captionWords.ts'

const cap = { kind: 'caption' as const, text: '7:40 am · coffee run', sub: 'Butler Library' }

test('a caption reads place first, then its line, and round-trips', () => {
  assert.equal(wordsOf(cap), 'Butler Library\n7:40 am · coffee run')
  assert.equal(wordsPatch(cap, wordsOf(cap)), null)
})

test('typing changes only what changed', () => {
  assert.deepEqual(wordsPatch(cap, 'Butler Library\nLunch 😋'), { text: 'Lunch 😋' })
  assert.deepEqual(wordsPatch(cap, 'Lunch 😋'), { text: 'Lunch 😋', sub: '' })
  assert.deepEqual(wordsPatch({ kind: 'title', text: 'Sep 22', sub: '' }, 'Sep 22\nday one'), { sub: 'day one' })
})

test('a date keeps one line and an emptied box changes nothing', () => {
  assert.deepEqual(wordsPatch({ kind: 'date', text: 'Sep 22', sub: '' }, 'Sep\n23'), { text: 'Sep 23' })
  assert.equal(wordsPatch(cap, '  \n '), null)
})

test('while typing, the box sizes itself on what is typed, not what was saved', () => {
  const h = { kind: 'heading' as const, text: 'Lunch', sub: 'so good', id: 'h' }
  assert.deepEqual(asTyped(h, 'My Way To School\nso good'), { ...h, text: 'My Way To School' })
  assert.deepEqual(asTyped(h, ''), h, 'an emptied box keeps the saved words to measure')
})
