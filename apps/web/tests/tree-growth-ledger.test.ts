import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { CourseTree, NotebookRead } from '../src/types'
import { canPlayGrowth, GrowthLedger, LEGACY_GROWTH_STORAGE_KEY, sectionGrowthKey, treeGrowthEnabled } from '../src/features/tree/growth/ledger.ts'

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    has: (key: string) => values.has(key),
  }
}

function makeTree(courseId: string, notebooks: Array<{ id: string; sections: Array<{ id: string; block_id?: string; title?: string }> }>): CourseTree {
  return {
    course_id: courseId,
    notebooks: notebooks.map(book => {
      const chapter = {
        id: 'chapter', title: '第一章', chapter_order: 0, status: 'active', deleted_at: null,
        sections: book.sections.map((section, index) => ({
          id: section.id, block_id: section.block_id, title: section.title ?? '标题', section_order: index,
          course_id: courseId, knowledge_node_id: '', material_id: null, section_key: null,
          revision_number: 1, user_locked: false, updated_at: '',
        })),
      }
      return {
        id: book.id, course_id: courseId, chapters: [chapter],
        historical_sections: [], removed_chapters: [], tree_slot: 0, title: book.id,
      } as unknown as NotebookRead
    }),
  }
}

<<<<<<< HEAD
test('growth is enabled by default and reduced motion or offscreen content cannot animate', () => {
  assert.equal(treeGrowthEnabled(undefined), true)
=======
test('the feature is opt-in and reduced motion or offscreen content cannot animate', () => {
  assert.equal(treeGrowthEnabled(undefined), false)
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
  assert.equal(treeGrowthEnabled('false'), false)
  assert.equal(treeGrowthEnabled('true'), true)
  assert.equal(canPlayGrowth(false, false, true), false)
  assert.equal(canPlayGrowth(true, true, true), false)
  assert.equal(canPlayGrowth(true, false, false), false)
  assert.equal(canPlayGrowth(true, false, true), true)
})

test('initial directory load seeds a baseline; block IDs deduplicate across refreshes and title changes', () => {
  const ledger = new GrowthLedger(memoryStorage())
  const initial = makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row-1', block_id: 'heading-1', title: '旧标题' }] }])
  ledger.observeDirectory(initial)
  assert.deepEqual(ledger.pending(), [])

  const renamed = makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'rebuilt-row', block_id: 'heading-1', title: '新标题' }] }])
  ledger.observeDirectory(renamed)
  ledger.observeDirectory(renamed)
  assert.deepEqual(ledger.pending(), [])

  const added = makeTree('course-a', [{ id: 'book-a', sections: [
    { id: 'rebuilt-row', block_id: 'heading-1', title: '新标题' },
    { id: 'row-2', block_id: 'heading-2', title: '新章节' },
  ] }])
  ledger.observeDirectory(added)
  ledger.observeDirectory(added)
  assert.deepEqual(ledger.pending(), [{ kind: 'section', id: 'heading-2', courseId: 'course-a', notebookId: 'book-a' }])
  assert.equal(sectionGrowthKey('book-a', 'heading-2'), JSON.stringify(['book-a', 'heading-2']))
})

<<<<<<< HEAD
test('new courses receive one growth receipt and deleting a course cancels an unplayed receipt', () => {
  const ledger = new GrowthLedger(memoryStorage())
  ledger.observeCourses(['course-a'])
  assert.deepEqual(ledger.pending(), [])
  ledger.observeCourses(['course-a', 'course-b'])
  assert.deepEqual(ledger.pending(), [{ kind: 'course', id: 'course-b', courseId: 'course-b' }])
  ledger.observeCourses(['course-a'])
  assert.deepEqual(ledger.pending(), [])
  ledger.observeCourses(['course-a', 'course-b'])
  assert.deepEqual(ledger.pending(), [])
})

=======
>>>>>>> b1d87ea547afebb87e48c63ffee93792239fc846
test('new notebook owns its section namespace and does not inherit legacy row IDs', () => {
  const ledger = new GrowthLedger(memoryStorage())
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'same-row', block_id: 'same-block' }] }]))
  ledger.observeDirectory(makeTree('course-a', [
    { id: 'book-a', sections: [{ id: 'same-row', block_id: 'same-block' }] },
    { id: 'book-b', sections: [{ id: 'same-row', block_id: 'same-block' }, { id: 'legacy-only' }] },
  ]))
  assert.deepEqual(ledger.pending(), [{ kind: 'notebook', id: 'book-b', courseId: 'course-a', notebookId: 'book-b' }])
  ledger.consume(ledger.pending())
  ledger.observeDirectory(makeTree('course-a', [
    { id: 'book-a', sections: [{ id: 'same-row', block_id: 'same-block' }] },
    { id: 'book-b', sections: [
      { id: 'same-row', block_id: 'same-block' }, { id: 'legacy-only' },
      { id: 'row-new', block_id: 'new-block' },
    ] },
  ]))
  assert.deepEqual(ledger.pending(), [{ kind: 'section', id: 'new-block', courseId: 'course-a', notebookId: 'book-b' }])
})

test('a replaced block ID is a new anchor, while deleted and restored stable IDs do not replay', () => {
  const ledger = new GrowthLedger(memoryStorage())
  const original = makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row', block_id: 'block-old' }] }])
  ledger.observeDirectory(original)
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row', block_id: 'block-new' }] }]))
  assert.deepEqual(ledger.pending().map(event => event.id), ['block-new'])
  ledger.consume(ledger.pending())
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [] }]))
  ledger.observeDirectory(original)
  assert.deepEqual(ledger.pending(), [])
})

test('an empty Notebook seeds no leaves and later content is scoped to its stable block ID', () => {
  const ledger = new GrowthLedger(memoryStorage())
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [] }]))
  assert.deepEqual(ledger.pending(), [])
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row', block_id: 'first-heading' }] }]))
  assert.deepEqual(ledger.pending(), [{ kind: 'section', id: 'first-heading', courseId: 'course-a', notebookId: 'book-a' }])
})

test('course deletion discards queued events and restoration does not replay them', () => {
  const ledger = new GrowthLedger(memoryStorage())
  const original = makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row', block_id: 'block-a' }] }])
  ledger.observeDirectory(original)
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [
    { id: 'row', block_id: 'block-a' }, { id: 'new-row', block_id: 'block-b' },
  ] }]))
  assert.equal(ledger.pending().length, 1)
  ledger.observeCourses([])
  assert.deepEqual(ledger.pending(), [])
  ledger.observeCourses(['course-a'])
  ledger.observeDirectory(original)
  assert.deepEqual(ledger.pending(), [])
})

test('Notebook deletion discards a queued leaf and restoring that Notebook stays quiet', () => {
  const ledger = new GrowthLedger(memoryStorage())
  const original = makeTree('course-a', [{ id: 'book-a', sections: [{ id: 'row', block_id: 'block-a' }] }])
  ledger.observeDirectory(original)
  ledger.observeDirectory(makeTree('course-a', [{ id: 'book-a', sections: [
    { id: 'row', block_id: 'block-a' }, { id: 'new-row', block_id: 'block-b' },
  ] }]))
  ledger.observeDirectory(makeTree('course-a', []))
  assert.deepEqual(ledger.pending(), [])
  ledger.observeDirectory(original)
  assert.deepEqual(ledger.pending(), [])
})

test('storage v1 note events are ignored and left untouched', () => {
  const storage = memoryStorage({
    [LEGACY_GROWTH_STORAGE_KEY]: JSON.stringify({ version: 1, events: [{ kind: 'note', id: 'old-note', courseId: 'course-a' }] }),
  })
  const ledger = new GrowthLedger(storage)
  assert.deepEqual(ledger.pending(), [])
  ledger.observeDirectory(makeTree('course-a', []))
  assert.equal(storage.has(LEGACY_GROWTH_STORAGE_KEY), true)
  assert.deepEqual(ledger.pending(), [])
})
