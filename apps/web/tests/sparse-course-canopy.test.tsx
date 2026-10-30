import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { courseCanopyGeometry, forestCanopyGeometry } from '../src/features/tree/courseCanopyGeometry'
import { notebookGeometry } from '../src/features/tree/treeGeometry'
import { HomeCourseTree } from '../src/features/home/HomeCourseTree'
import { KnowledgeTreeScene } from '../src/features/tree/KnowledgeTreeScene'
import type { ForestCourse } from '../src/features/forest/types'
import type { NotebookRead } from '../src/types'

afterEach(cleanup)
function books(count: number): NotebookRead[] {
  return Array.from({ length: count }, (_, b) => ({ id: `book-${b}`, course_id: 'course', title: `笔记本${b}`, tree_slot: b, order_revision: 0, historical_sections: [], removed_chapters: [], chapters: [{ id: `material-${b}`, title: '第一讲', chapter_order: 0, status: 'completed', deleted_at: null, sections: Array.from({ length: 6 }, (_, i) => ({ id: `note-${b}-${i}`, notebook_id: `book-${b}`, material_id: `material-${b}`, tree_slot: i, section_order: i, section_key: `${i}`, title: `知识${b}-${i}`, knowledge_node_id: null, revision_number: 1, user_locked: false, updated_at: '' })) }] }))
}

test.each([1, 2, 3])('%i notebooks have one main branch each while filling the crown without copying knowledge points', count => {
  const data = books(count)
  for (const canopy of [courseCanopyGeometry('course', data), forestCanopyGeometry('course', data.map(notebookGeometry), new Set(), '')]) {
    expect(canopy.items).toHaveLength(count)
    expect(canopy.items.map(item => item.book.id)).toEqual(data.map(book => book.id))
    expect(canopy.items.flatMap(item => item.branch.limbs.filter(limb => limb.level === 1))).toHaveLength(count)
    const leaves = canopy.items.flatMap(item => item.leaves)
    expect(leaves).toHaveLength(count * 6)
    expect(new Set(leaves.map(leaf => leaf.section.id)).size).toBe(count * 6)
    expect(Math.min(...leaves.map(leaf => leaf.x))).toBeLessThan(-100)
    expect(Math.max(...leaves.map(leaf => leaf.x))).toBeGreaterThan(100)
    expect(Math.min(...leaves.map(leaf => leaf.y))).toBeLessThan(-600)
    for (const item of canopy.items) for (const leaf of item.leaves) expect(leaf.section.notebook_id).toBe(item.book.id)
  }
})

const course = { course_id: 'course', name: '课程', learning_state: 'learning', position: 0, revision: 0, prerequisites: [], note_count: 6, material_count: 1, semester: 1, level: 'foundation' } as ForestCourse

test.each(['home', 'forest'])('an empty course in %s has bare branches and no decorative knowledge leaves', mode => {
  const { container } = mode === 'home'
    ? render(<HomeCourseTree courseId="course" books={[]} previewId="preview" onPreview={vi.fn()} onLeave={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
    : render(<KnowledgeTreeScene courses={[{ ...course, note_count: 0, material_count: 0 }]} trees={[{ course_id: 'course', notebooks: [] }]} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} onRelation={vi.fn()} />)
  expect(container.querySelectorAll('image[href="/assets/forest/leaves-atlas.webp"]')).toHaveLength(0)
  expect(container.querySelectorAll('.kt-sapling-bough').length).toBeGreaterThan(0)
  expect(screen.queryByRole('button', { name: /打开知识点/ })).toBeNull()
})

test.each([1, 2])('revealing or expanding distant notes keeps the first leaves fixed with %i notebooks', count => {
  const data = books(count)
  data[0].chapters[0].sections = Array.from({ length: 200 }, (_, i) => ({ ...data[0].chapters[0].sections[0], id: `note-0-${i}`, tree_slot: i }))
  const branches = data.map(notebookGeometry)
  const original = forestCanopyGeometry('course', branches, new Set(), '').items.flatMap(item => item.leaves)
  for (const changed of [forestCanopyGeometry('course', branches, new Set(['note-0-199']), ''), forestCanopyGeometry('course', branches, new Set(), '', 'book-0')]) {
    const leaves = changed.items.flatMap(item => item.leaves)
    for (const leaf of original) expect(leaves.find(next => next.section.id === leaf.section.id)).toEqual(leaf)
  }
})
test.each(['home', 'forest'])('one notebook keeps one keyboard entry and exact leaf ownership in %s', mode => {
  const data = books(1), onBook = vi.fn(), onNote = vi.fn()
  if (mode === 'home') render(<HomeCourseTree courseId="course" books={data} previewId="preview" onPreview={vi.fn()} onLeave={vi.fn()} onNotebook={onBook} onNote={onNote} />)
  else render(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: data }]} onRoot={vi.fn()} onNotebook={onBook} onNote={onNote} onRelation={vi.fn()} />)
  fireEvent.keyDown(screen.getByRole('button', { name: '续读笔记本：笔记本0' }), { key: 'Enter' })
  expect(onBook).toHaveBeenCalledTimes(1)
  for (const section of data[0].chapters[0].sections) {
    fireEvent.click(screen.getByRole('button', { name: `打开知识点：${section.title}` }))
    expect(onNote).toHaveBeenLastCalledWith(...(mode === 'home' ? [data[0], section] : ['course', data[0].id, section]))
  }
})
