import assert from 'node:assert/strict'
import { test } from 'node:test'
import { forestLayout, signature } from '../src/features/tree/layout.ts'

const course = (id: string, semester = 1, position = 0, level = 'foundation') => ({
  course_id: id,
  name: id,
  semester,
  position,
  level,
  learning_state: 'planned',
  revision: 0,
  note_count: 0,
  material_count: 0,
  prerequisites: [],
})

test('forest follows semester and manual order with stable natural variation', () => {
  const input = [
    course('b', 2, 0, 'application'),
    course('a', 1, 1),
    course('c', 1, 0, 'professional'),
  ]
  const first = forestLayout(input as never)
  assert.deepEqual(
    first.map((tree) => tree.course.course_id),
    ['c', 'a', 'b'],
  )
  assert.deepEqual(forestLayout(input as never), first)
  assert.equal(first[0].y < first[1].y, true)
  assert.equal(first[2].y < first[0].y, true)
  assert.deepEqual(forestLayout([...input, course('later', 3, 0)] as never).slice(0, 3), first)
})

test('persisted slots keep existing course positions when courses are appended', () => {
  const input = [course('a'), course('b', 2)]
  const original = forestLayout(input as never)
  const saved = Object.fromEntries(
    original.map((tree) => [
      tree.course.course_id,
      { x: tree.x, signature: signature(tree.course) },
    ]),
  )
  const next = forestLayout([course('new', 1, 2), ...input] as never, saved)
  for (const tree of original)
    assert.equal(next.find((item) => item.course.course_id === tree.course.course_id)?.x, tree.x)
})

test('explicit semester or ordering changes move the course, while level changes keep its slot', () => {
  const input = [course('a', 1, 0), course('b', 1, 1), course('c', 2, 2)]
  const before = forestLayout(input as never)
  const saved = Object.fromEntries(
    before.map((tree) => [tree.course.course_id, { x: tree.x, signature: signature(tree.course) }]),
  )
  const changed = forestLayout([input[0], input[1], course('c', 1, -1)] as never, saved)
  assert.equal(changed[0].course.course_id, 'c')
  assert.equal(changed[0].x < changed[1].x, true)
  const raised = forestLayout(
    [input[0], course('b', 1, 1, 'application'), input[2]] as never,
    saved,
  )
  assert.equal(raised[1].x, before[1].x)
  assert.equal(raised[1].y < before[1].y, true)
})
