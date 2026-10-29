import { beforeEach, expect, test } from 'vitest'
import { GrowthLedger } from '../src/features/tree/growth/ledger'
import type { CourseTree } from '../src/types'
import type { NotebookRelation } from '../src/features/forest/types'

const directory = (blocks = ['old'], books = ['book']): CourseTree => ({
  course_id: 'course',
  notebooks: books.map(id => ({
    id, course_id: 'course', title: id, tree_slot: 0,
    chapters: [{ id: 'material', status: 'completed', sections: blocks.map(block_id => ({
      id: `row-${block_id}`, block_id, material_id: 'material', notebook_id: id,
      title: block_id, tree_slot: 0,
    })) }],
    historical_sections: [], removed_chapters: [],
  })),
}) as CourseTree
const relation = (id: string, stale = false): NotebookRelation => ({
  id, source_course_id: 'course', target_course_id: 'other',
  source_notebook_id: 'book', target_notebook_id: 'other-book',
  source_block_id: 'old', target_block_id: 'other-block',
  source_title: 'source', target_title: 'target',
  source_course_name: 'course', target_course_name: 'other',
  relation_type: 'related', reason: 'related', created_at: '',
  stale, origin: 'manual',
})
let ledger: GrowthLedger
beforeEach(() => {
  let raw: string | null = null
  ledger = new GrowthLedger({ getItem: () => raw, setItem: (_: string, value: string) => { raw = value } })
})

test('initial lazy data is a baseline; only actual block additions grow and removed IDs stay known', () => {
  ledger.observeDirectory(directory())
  expect(ledger.pending()).toEqual([])
  ledger.observeDirectory(directory(['old', 'new']))
  expect(ledger.pending().map(event => [event.kind, event.id])).toEqual([['section', 'new']])
  ledger.consume(ledger.pending())
  ledger.observeDirectory(directory([]))
  ledger.observeDirectory(directory(['old', 'new']))
  expect(ledger.pending()).toEqual([])
})

test('creation survives navigation and a consumed course ID cannot replay after reload', () => {
  let raw: string | null = null
  const storage = { getItem: () => raw, setItem: (_: string, value: string) => { raw = value } }
  ledger = new GrowthLedger(storage)
  ledger.observeCourses([])
  ledger.observeCourses(['course'])
  ledger = new GrowthLedger(storage)
  expect(ledger.pending().map(event => event.id)).toEqual(['course'])
  ledger.consume(ledger.pending())
  ledger = new GrowthLedger(storage)
  ledger.observeCourses(['course'])
  expect(ledger.pending()).toEqual([])
})

test('new material sections grow after an old directory baseline without replaying old blocks', () => {
  ledger.observeDirectory(directory(['old']))
  const next = directory(['old'])
  next.notebooks[0].chapters.push({
    id: 'new-material', status: 'completed', sections: [{
      id: 'generated-row', block_id: 'generated', material_id: 'new-material',
      notebook_id: 'book', title: 'generated',
    }],
  } as never)
  ledger.observeDirectory(next)
  expect(ledger.pending().map(event => event.id)).toEqual(['generated'])
})

test('first relation read and regrouping are static, a new valid relation grows once', () => {
  ledger.observeRelations([relation('old')])
  ledger.observeRelations([relation('old'), relation('new')])
  expect(ledger.pending().map(event => event.id)).toEqual(['new'])
  ledger.consume(ledger.pending())
  ledger.observeRelations([relation('new', true)])
  ledger.observeRelations([relation('new'), relation('old')])
  expect(ledger.pending()).toEqual([])
})

test('section refresh detects only new stable block IDs and ignores metadata changes', () => {
  ledger.observeDirectory(directory(['old']))
  const renamed = directory(['old'])
  renamed.notebooks[0].chapters[0].sections[0].title = 'renamed'
  ledger.observeDirectory(renamed)
  expect(ledger.pending()).toEqual([])
  ledger.observeDirectory(directory(['old', 'added']))
  expect(ledger.pending().map(event => [event.kind, event.id])).toEqual([['section', 'added']])
})

test('restoration establishes a baseline and blocked storage cannot break later writes', () => {
  ledger = new GrowthLedger({ getItem: () => { throw Error('blocked') }, setItem: () => { throw Error('quota') } })
  ledger.observeDirectory(directory(['old-imported'], ['bound']))
  expect(ledger.pending()).toEqual([])
  ledger.observeDirectory(directory(['old-imported'], ['bound', 'new-book']))
  expect(ledger.pending().map(event => event.id)).toEqual(['new-book'])
})

test('a write-only storage quota failure keeps the in-memory receipt across observations', () => {
  ledger = new GrowthLedger({ getItem: () => null, setItem: () => { throw Error('quota') } })
  ledger.observeCourses([])
  ledger.observeCourses(['course'])
  expect(ledger.pending().map(event => event.id)).toEqual(['course'])
  ledger.observeDirectory(directory())
  ledger.consume(ledger.pending())
  ledger.observeDirectory(directory())
  expect(ledger.pending()).toEqual([])
})

test('restored material present in the first directory is static; later additions grow', () => {
  ledger.observeDirectory(directory(['restored']))
  expect(ledger.pending()).toEqual([])
  ledger.observeDirectory(directory(['restored', 'new']))
  expect(ledger.pending().map(event => event.id)).toEqual(['new'])
})

test('removing a Notebook clears its unplayed child event and restoration stays quiet', () => {
  ledger.observeDirectory(directory(['old']))
  ledger.observeDirectory(directory(['old', 'new']))
  expect(ledger.pending().map(event => event.id)).toEqual(['new'])
  ledger.observeDirectory(directory([], []))
  expect(ledger.pending()).toEqual([])
  ledger.observeDirectory(directory(['old', 'new']))
  expect(ledger.pending()).toEqual([])
})

test('restoring material cancels an unplayed section event for a removed block', () => {
  ledger.observeDirectory(directory([]))
  ledger.observeDirectory(directory(['restored']))
  expect(ledger.pending().map(event => event.id)).toEqual(['restored'])
  ledger.observeDirectory(directory([]))
  ledger.observeDirectory(directory(['restored']))
  expect(ledger.pending()).toEqual([])
})
