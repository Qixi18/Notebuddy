import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  forestLayout,
  signature,
  visibleCourses,
  treeLeaves,
} from '../src/features/forest/layout.ts'

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

test('camera fetches visible and adjacent trees rather than every course', () => {
  const trees = forestLayout(
    Array.from({ length: 60 }, (_, i) => course(`c${i}`, Math.floor(i / 8) + 1, i)) as never,
  )
  const visible = visibleCourses(trees, { x: 0, y: 0, k: 1 }, 1100)
  assert.equal(visible.length >= 2 && visible.length <= 6, true)
  assert.equal(visible.includes('c59'), false)
})

test('overview uses at most 12 actual note leaves and focus keeps exact notes', () => {
  const sections = Array.from({ length: 30 }, (_, i) => ({
    id: `note-${i}`,
    material_id: 'lecture',
    title: `topic-${i}`,
    section_order: i,
  }))
  const book = {
    chapters: [{ id: 'lecture', sections }],
    historical_sections: [],
    removed_chapters: [],
  }
  assert.equal(treeLeaves(book as never).length, 12)
  assert.equal(treeLeaves(book as never, new Set(['lecture'])).length, 30)
  assert.deepEqual(treeLeaves({ ...book, chapters: [] } as never), [])
  assert.equal(treeLeaves(book as never)[0].section.id, 'note-0')
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

test('adding a lecture or section preserves existing leaf positions', () => {
  const section = (id: string, order: number) => ({
    id,
    material_id: 'lecture',
    title: id,
    section_order: order,
  })
  const before = {
    chapters: [{ id: 'lecture', sections: [section('old', 0)] }],
    historical_sections: [],
    removed_chapters: [],
  }
  const after = {
    ...before,
    chapters: [
      { ...before.chapters[0], sections: [section('old', 0), section('new', 1)] },
      { id: 'next', sections: [] },
    ],
  }
  assert.deepEqual(treeLeaves(after as never)[0], treeLeaves(before as never)[0])
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

test('overview distributes leaves across actual chapters and includes confirmed vine endpoints', () => {
  const chapters = Array.from({ length: 4 }, (_, chapter) => ({
    id: `m${chapter}`,
    title: `Lecture ${chapter}`,
    sections: Array.from({ length: 20 }, (_, i) => ({
      id: `n${chapter}-${i}`,
      material_id: `m${chapter}`,
      section_order: i,
      title: `Topic ${i}`,
    })),
  }))
  const book = { chapters, historical_sections: [], removed_chapters: [] }
  const overview = treeLeaves(book as never)
  assert.equal(new Set(overview.map((leaf) => leaf.chapterId)).size, 4)
  const endpoint = treeLeaves(book as never, undefined, new Set(['n3-18']))
  assert.equal(endpoint.length, 13)
  assert.equal(
    endpoint.some((leaf) => leaf.section.id === 'n3-18'),
    true,
  )
  assert.deepEqual(endpoint.slice(0, 12), overview)
})

test('two-lecture overview and focus with neighboring endpoint keep actual leaves apart', () => {
  const chapters = Array.from({ length: 2 }, (_, chapter) => ({
    id: `m${chapter}`,
    title: `Lecture ${chapter}`,
    sections: Array.from({ length: 20 }, (_, i) => ({
      id: `n${chapter}-${i}`,
      material_id: `m${chapter}`,
      section_order: i,
      title: `Topic ${i}`,
    })),
  }))
  const book = { chapters, historical_sections: [], removed_chapters: [] }
  for (const leaves of [
    treeLeaves(book as never),
    treeLeaves(book as never, new Set(['m0']), new Set(['n1-4'])),
  ]) {
    const first = leaves.find((leaf) => leaf.section.id === 'n0-0')!
    const neighbor = leaves.find((leaf) => leaf.section.id === 'n1-4')!
    assert.equal(Math.abs(first.x - neighbor.x) >= 42 || Math.abs(first.y - neighbor.y) >= 56, true)
  }
})
