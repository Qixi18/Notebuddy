import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { HomeCourseGarden } from '../src/features/home/HomeCourseGarden'
import type { ForestCourse, TreeRelation } from '../src/features/forest/types'
import type { CourseTree } from '../src/types'
import { courseCanopyGeometry } from '../src/features/tree/courseCanopyGeometry'
import { pointAt } from '../src/features/tree/naturalBranchGeometry'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const courses = ['a', 'b', 'c'].map((id, i) => ({ course_id: id, name: `课程${id}`, position: i, learning_state: 'learning' })) as ForestCourse[]
const trees = courses.map(course => ({ course_id: course.course_id, notebooks: Array.from({ length: 5 }, (_, b) => ({ id: `${course.course_id}-book-${b}`, course_id: course.course_id, tree_slot: b, title: `笔记本${b}`, chapters: [{ id: `m-${b}`, sections: [{ id: `${course.course_id}-note-${b}`, title: `知识${b}`, notebook_id: `${course.course_id}-book-${b}`, tree_slot: 0 }] }], historical_sections: [] })) })) as CourseTree[]
const relations = Array.from({ length: 5 }, (_, i) => ({ id: `relation-${i}`, source_course_id: 'a', target_course_id: 'b', source_block_id: `a-note-${i}`, target_block_id: `b-note-${i}`, source_title: `起点${i}`, target_title: `终点${i}`, source_course_name: '课程a', target_course_name: '课程b', status: 'confirmed', stale: false, reason: `原始依据${i}`, origin: 'ai' })) as TreeRelation[]
function sizes(width = 480) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1000, height: 600, left: 0, top: 0 } as DOMRect)
  vi.spyOn(SVGSVGElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: SVGSVGElement) {
    const id = this.closest('[data-course-id]')?.getAttribute('data-course-id')
    return { left: id === 'c' ? (width + 40) * 2 : id === 'b' ? width + 40 : 0, top: 0, width, height: 390 } as DOMRect
  })
}

it('draws the same grouped vines on home and opens the exact original relation', async () => {
  sizes()
  const onRelation = vi.fn()
  const { container } = render(<HomeCourseGarden courses={courses} trees={trees} relations={relations} onRelation={onRelation} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  await waitFor(() => expect(container.querySelectorAll('.kt-vine')).toHaveLength(4))
  expect(new Set([...container.querySelectorAll('[data-vine-members]')].flatMap(el => el.getAttribute('data-vine-members')!.split('|'))).size).toBe(5)
  fireEvent.click(screen.getAllByRole('button', { name: /查看课程a与课程b的/ })[0])
  const item = screen.getAllByRole('button', { name: /起点\d+.*终点\d+/ })[0]
  const index = Number(item.textContent!.match(/起点(\d+)/)![1])
  fireEvent.click(item)
  expect(onRelation).toHaveBeenCalledExactlyOnceWith(relations[index])
  expect(screen.queryByRole('button', { name: '放大知识树' })).toBeNull()
  expect(screen.queryByRole('button', { name: '下一组课程' })).toBeNull()
})

it('keeps the third course and its vine available in the same home view', async () => {
  sizes(300)
  const third = { ...relations[0], id: 'third', source_course_id: 'b', target_course_id: 'c', source_block_id: 'b-note-0', target_block_id: 'c-note-0', source_course_name: '课程b', target_course_name: '课程c' }
  const onRelation = vi.fn()
  const { container } = render(<HomeCourseGarden courses={courses} trees={trees} relations={[third]} onRelation={onRelation} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  await waitFor(() => expect(container.querySelector('[data-vine-members="third"]')).toBeTruthy())
  expect(screen.getByRole('heading', { name: '课程c' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /查看课程b与课程c的1条知识联系/ }))
  fireEvent.click(within(screen.getByRole('dialog', { name: '藤蔓上的知识联系' })).getByRole('button', { name: /起点0.*终点0/ }))
  expect(onRelation).toHaveBeenCalledExactlyOnceWith(third)
})

it('retains the third side of a three-course triangle', async () => {
  sizes(300)
  const across = { ...relations[0], id: 'across', source_course_id: 'a', target_course_id: 'c', source_block_id: 'a-note-0', target_block_id: 'c-note-0', target_course_name: '课程c' }
  const { container } = render(<HomeCourseGarden courses={courses} trees={trees} relations={[across]} onRelation={vi.fn()} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  await waitFor(() => expect(container.querySelector('[data-vine-members="across"]')).toBeTruthy())
})

it('updates vine grafts after a different preview notebook is selected', async () => {
  sizes()
  const { container } = render(<HomeCourseGarden courses={courses.slice(0, 2)} trees={trees} relations={relations} onRelation={vi.fn()} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} />)
  await waitFor(() => expect(container.querySelector('.vine-outline')).toBeTruthy())
  const before = container.querySelector('.vine-outline')!.getAttribute('d')
  fireEvent.change(screen.getByLabelText('课程a的笔记本目录'), { target: { value: 'a-book-4' } })
  await waitFor(() => expect(container.querySelector('.vine-outline')!.getAttribute('d')).not.toBe(before))
})

it('grafts runtime AI results onto their own notebook branches and follows updated endpoints', async () => {
  sizes()
  const props = { courses: courses.slice(0, 2), trees, onRelation: vi.fn(), onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn() }
  const view = render(<HomeCourseGarden {...props} relations={[relations[0]]} />)
  const canopy = courseCanopyGeometry('a', trees[0].notebooks)
  const expectSource = async (bookId: string) => {
    const svg = view.container.querySelector('.home-course-tree')!
    const [x, y, width, height] = svg.getAttribute('viewBox')!.split(' ').map(Number)
    const scale = Math.min(480 / width, 390 / height)
    const root = { x: ((480 - width * scale) / 2 - x * scale) / scale, y: (390 - height * scale - y * scale) / scale }
    const branch = canopy.items.find(item => item.book.id === bookId)?.branch
    const local = branch ? pointAt(branch.primary.curves, .7) : { x: -8, y: -180 }
    await waitFor(() => {
      const path = view.container.querySelector('.vine-focus')!.getAttribute('d')!
      const [startX, startY] = path.match(/^M([^ ]+)/)![1].split(',').map(Number)
      expect(startX).toBeCloseTo(root.x + local.x, 2)
      expect(startY).toBeCloseTo(root.y + local.y, 2)
    })
  }
  await expectSource('a-book-0')
  view.rerender(<HomeCourseGarden {...props} relations={[{ ...relations[0], id: 'new-ai-result', source_block_id: 'a-note-2', target_block_id: 'b-note-2' }]} />)
  await expectSource('a-book-2')
  view.rerender(<HomeCourseGarden {...props} relations={[{ ...relations[0], id: 'outside-preview', source_block_id: 'a-note-4', target_block_id: 'b-note-4' }]} />)
  await expectSource('a-book-4')
  view.rerender(<HomeCourseGarden {...props} relations={[]} />)
  await waitFor(() => expect(view.container.querySelector('.kt-vine')).toBeNull())
})
