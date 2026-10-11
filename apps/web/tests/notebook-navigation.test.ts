import assert from 'node:assert/strict'
import { test } from 'node:test'
import { adjacentSection, mergeNotebookNotes, notebookPath, resolveSection, shouldBlockNoteNavigation } from '../src/features/notebook/navigation.ts'

const outline = { chapters: [
  { id: 'm1', sections: [{ id: 'n1', material_id: 'm1', knowledge_node_id: 'k' }] },
  { id: 'm2', sections: [{ id: 'n2', material_id: 'm2', knowledge_node_id: 'k' }] },
], historical_sections: [{ id: 'old', material_id: null, knowledge_node_id: 'k' }], removed_chapters: [] }

test('same concept in different lectures resolves the exact note', () => {
  assert.equal(resolveSection(outline, 'm2', 'n2')?.id, 'n2')
  assert.equal(resolveSection(outline, 'm1', 'n2'), undefined)
  assert.equal(resolveSection(outline, undefined, 'old')?.id, 'old')
  assert.equal(resolveSection(outline, undefined, 'unknown'), undefined)
  assert.equal(notebookPath('c', outline.chapters[1].sections[0]), '/courses/c/notebook?chapter=m2&section=n2')
})

test('next and previous follow chapter order and retain IDs', () => {
  assert.equal(adjacentSection(outline, 'n1', 1)?.id, 'n2')
  assert.equal(adjacentSection(outline, 'n2', -1)?.id, 'n1')
  assert.equal(adjacentSection(outline, 'n1', -1), undefined)
})

test('query-only navigation protects a dirty section draft', () => {
  const here = { pathname: '/courses/c/notebook', search: '?section=n1' }
  const there = { ...here, search: '?section=n2' }
  assert.equal(shouldBlockNoteNavigation(true, here, there), true)
  assert.equal(shouldBlockNoteNavigation(false, here, there), false)
  assert.equal(shouldBlockNoteNavigation(true, here, here), false)
})

test('a late chapter response cannot replace a newer saved revision', () => {
  const current = [{ id: 'n1', revision_number: 2, content: 'user save' }]
  const incoming = [{ id: 'n1', revision_number: 1, content: 'old chapter' }, { id: 'n2', revision_number: 1, content: 'next' }]
  assert.deepEqual(mergeNotebookNotes(current, incoming), [current[0], incoming[1]])
})
