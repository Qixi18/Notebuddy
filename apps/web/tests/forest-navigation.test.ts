import assert from 'node:assert/strict'
import { test } from 'node:test'
import { forestNotePath, restoreForestState } from '../src/features/forest/navigation.ts'

test('forest opens the independent note and carries a return location', () => {
  assert.equal(
    forestNotePath('course-b', { id: 'note-b', material_id: 'lecture-b' }),
    '/courses/course-b/notebook?chapter=lecture-b&section=note-b',
  )
})

test('restore rejects invalid camera and preserves focus and chapters', () => {
  assert.deepEqual(
    restoreForestState('{"camera":{"x":-800,"y":10,"k":1.3},"focus":"c","expanded":["m"]}'),
    { camera: { x: -800, y: 10, k: 1.3 }, focus: 'c', expanded: ['m'] },
  )
  assert.equal(restoreForestState('{"camera":{"x":0,"y":0,"k":0}}'), undefined)
  assert.equal(restoreForestState('broken'), undefined)
})

test('restore retains measured viewport dimensions and safely accepts old views', () => {
  const old = { camera: { x: 12, y: -360, k: 1.05 }, focus: 'c', expanded: ['m'] }
  const measured = { ...old, viewport: { width: 664, height: 523 } }
  assert.deepEqual(restoreForestState(JSON.stringify(measured)), measured)
  assert.deepEqual(restoreForestState(JSON.stringify(old)), old)
  assert.deepEqual(
    restoreForestState(JSON.stringify({ ...old, viewport: { width: 0, height: 'bad' } })),
    old,
  )
})
