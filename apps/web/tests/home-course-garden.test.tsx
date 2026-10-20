import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { CourseTree } from '../src/types'
import type { ForestCourse } from '../src/features/forest/types'
import { HomeCourseGarden } from '../src/features/home/HomeCourseGarden'
import { api } from '../src/api'

vi.mock('../src/api', () => ({ api: { getNote: vi.fn(async (id: string) => ({ id, course_id: 'c0', notebook_id: `b${id[4]}`, content_markdown: '# 标题\n\n## 一句话理解\n\n这是从真实笔记读取的内容预览。' })) } }))

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const courses = [0, 1, 2].map(index => ({ course_id: `c${index}`, name: `课程${index}`, learning_state: 'learning', note_count: 8, material_count: 2, prerequisites: [] })) as unknown as ForestCourse[]
const tree = { course_id: 'c0', notebooks: [0, 1, 2, 3].map(index => ({
  id: `b${index}`, course_id: 'c0', title: `笔记本${index}`, tree_slot: index, order_revision: 0,
  historical_sections: [], removed_chapters: [], chapters: [{ id: `m${index}`, title: '第一讲', status: 'completed', sections: Array.from({ length: 8 }, (_, n) => ({
    id: `note${index}-${n}`, notebook_id: `b${index}`, material_id: `m${index}`, title: `知识点${index}-${n}`, tree_slot: n,
  })) }],
})) } as unknown as CourseTree

test('home fits two courses, pages through the third, and exposes no camera controls', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900, height: 700 } as DOMRect)
  const watch = vi.fn()
  const { container } = render(<HomeCourseGarden courses={courses} trees={[tree]} onVisibleCourseIdsChange={watch} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  expect(screen.getAllByRole('article')).toHaveLength(2)
  expect(screen.queryByRole('button', { name: '放大知识树' })).toBeNull()
  expect(container.querySelector('.kt-canvas')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '下一组课程' }))
  expect(screen.getAllByRole('article')).toHaveLength(1)
  expect(screen.getByRole('heading', { name: '课程2' })).toBeTruthy()
  expect(watch).toHaveBeenLastCalledWith(['c2'])
})

test('bare leaves show their own note preview on focus and retain exact navigation IDs', async () => {
  const notebook = vi.fn(), note = vi.fn(), root = vi.fn()
  const { container } = render(<HomeCourseGarden courses={courses.slice(0, 1)} trees={[tree]} onRoot={root} onNotebook={notebook} onNote={note} />)
  fireEvent.click(screen.getByRole('button', { name: '续读笔记本：笔记本0' }))
  expect(notebook).toHaveBeenLastCalledWith('c0', 'b0')
  const leaf = container.querySelector('[data-home-leaf-id="note0-0"]')!
  fireEvent.click(leaf)
  expect(note).toHaveBeenLastCalledWith('c0', 'b0', expect.objectContaining({ id: 'note0-0' }))
  expect(container.querySelectorAll('.home-leaf-index, .home-branch-index, .home-note-labels')).toHaveLength(0)
  expect(screen.queryByRole('tooltip')).toBeNull()
  fireEvent.focus(screen.getByRole('button', { name: '打开知识点：知识点0-0' }))
  const preview = await screen.findByRole('tooltip')
  expect(within(preview).getByText('知识点0-0')).toBeTruthy()
  expect(await within(preview).findByText('这是从真实笔记读取的内容预览。')).toBeTruthy()
  expect(api.getNote).toHaveBeenCalledWith('note0-0')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByRole('tooltip')).toBeNull()
  fireEvent.change(screen.getByLabelText('课程0的笔记本目录'), { target: { value: 'b3' } })
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识点3-0' }))
  expect(note).toHaveBeenLastCalledWith('c0', 'b3', expect.objectContaining({ id: 'note3-0' }))
  fireEvent.click(screen.getByRole('button', { name: '打开笔记本3的全部8个知识点' }))
  expect(notebook).toHaveBeenLastCalledWith('c0', 'b3')
  fireEvent.click(screen.getByRole('button', { name: '课程菜单：课程0' }))
  expect(root).toHaveBeenCalledWith('c0')
})

test('sparse persistent slots do not shrink the home tree or change note ownership', () => {
  const sparse = structuredClone(tree)
  sparse.notebooks[0].tree_slot = 90
  sparse.notebooks[0].chapters[0].sections.forEach((section, index) => { section.tree_slot = 300 + index })
  const onNote = vi.fn()
  const { container } = render(<HomeCourseGarden courses={courses.slice(0, 1)} trees={[{ course_id: 'c0', notebooks: [sparse.notebooks[0]] }]} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={onNote} />)
  const box = container.querySelector('.home-course-tree')!.getAttribute('viewBox')!.split(' ').map(Number)
  expect(box[3]).toBeLessThan(1000)
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识点0-0' }))
  expect(onNote).toHaveBeenLastCalledWith('c0', 'b0', expect.objectContaining({ id: 'note0-0', tree_slot: 300 }))
})

test('a planning course has no fabricated clickable knowledge leaves', () => {
  const { container } = render(<HomeCourseGarden courses={courses.slice(0, 1)} trees={[{ course_id: 'c0', notebooks: [] }]} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  expect(container.querySelectorAll('[data-home-leaf-id]')).toHaveLength(0)
  expect(screen.getByText('上传资料，让第一片知识叶子生长')).toBeTruthy()
})
