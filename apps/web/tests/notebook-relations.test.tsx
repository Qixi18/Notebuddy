import { expect, test } from 'vitest'
import type { CourseTree } from '../src/types'
import type { NotebookRelation } from '../src/features/forest/types'
import { projectDirectory, projectRelations, sceneBlockId } from '../src/features/forest/notebookRelations'
import { notebookPath } from '../src/features/notebook/navigation'

const tree = (course: string): CourseTree => ({ course_id: course, notebooks: [{
  id: `book-${course}`, course_id: course, title: '笔记', tree_slot: 0, order_revision: 0,
  chapters: [{ id: 'h-1', title: '正文', status: 'parsed', sections: [{
    id: 'h-1', block_id: 'h-1', notebook_id: `book-${course}`, material_id: null, title: '同名标题', tree_slot: 0,
  }] }], historical_sections: [], removed_chapters: [],
}] }) as CourseTree
const relation: NotebookRelation = {
  id: 'r', source_course_id: 'a', target_course_id: 'b', source_notebook_id: 'book-a',
  target_notebook_id: 'book-b', source_block_id: 'h-1', target_block_id: 'h-1',
  source_title: '笔记 A', target_title: '笔记 B', source_course_name: '课程 A', target_course_name: '课程 B',
  relation_type: 'related', reason: '内容相关', created_at: '',
}

test('same body block ID in different notebooks has distinct scene identity and raw deep links', () => {
  const original = tree('a')
  const a = projectDirectory(original), b = projectDirectory(tree('b'))
  const projected = projectRelations([relation], [a, b])[0]
  expect(projected.source_block_id).not.toBe(projected.target_block_id)
  expect(projected.source_block_id).toBe(sceneBlockId('book-a', 'h-1'))
  expect(notebookPath('a', a.notebooks[0].chapters[0].sections[0])).toBe('/courses/a/notebooks/book-a?section=h-1')
  expect(original.notebooks[0].chapters[0].sections[0].id).toBe('h-1')
  expect(projectDirectory(a)).toEqual(a)
})

test('missing or moved section anchors never connect to a different available leaf', () => {
  const directories = [projectDirectory(tree('a')), projectDirectory(tree('b'))]
  expect(projectRelations([{ ...relation, target_block_id: 'missing' }], directories)).toEqual([])
  expect(projectRelations([{ ...relation, source_course_id: 'other-course' }], directories)).toEqual([])
})

test('whole-notebook links use current display anchors while preserving inference and staleness', () => {
  const projected = projectRelations([{ ...relation, source_block_id: null, target_block_id: null,
    origin: 'ai', stale: true }], [projectDirectory(tree('a')), projectDirectory(tree('b'))])[0]
  expect(projected.origin).toBe('ai')
  expect(projected.stale).toBe(true)
  expect(projected.target_block_id).toBe(sceneBlockId('book-b', 'h-1'))
})
