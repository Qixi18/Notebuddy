import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeTreeScene } from '../src/features/tree/KnowledgeTreeScene'
import type { ForestCourse } from '../src/features/forest/types'
import type { NotebookRead, SectionRead } from '../src/types'
import type { TreeRelation } from '../src/features/forest/types'
import { forestCanopyGeometry } from '../src/features/tree/courseCanopyGeometry'
import { notebookGeometry } from '../src/features/tree/treeGeometry'
import { FOREST_LAYOUT_VERSION } from '../src/features/tree/forestGroveLayout'

afterEach(cleanup)
const course: ForestCourse = { course_id: 'c', name: '离散数学', semester: 1, level: 'foundation', learning_state: 'learning', position: 0, revision: 1, note_count: 1, material_count: 1, prerequisites: [] }
const section: SectionRead = { id: 'real-note', notebook_id: 'b', tree_slot: 37, knowledge_node_id: 'node', material_id: 'm', section_key: 's', section_order: 0, title: '命题逻辑', revision_number: 1, user_locked: false, updated_at: '' }
const book: NotebookRead = { id: 'b', course_id: 'c', tree_slot: 0, title: '数学笔记', order_revision: 0, chapters: [{ id: 'm', title: '第一讲', chapter_order: 0, status: 'completed', deleted_at: null, sections: [section] }], historical_sections: [], removed_chapters: [] }
const props = { courses: [course], trees: [{ course_id: 'c', notebooks: [book] }], onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }

it('uses the home natural forked crown and only prints the course name on the canvas', () => {
  const { container } = render(<KnowledgeTreeScene {...props} />)
  expect(container.querySelector('.home-natural-limb-2')).toBeTruthy()
  expect([...container.querySelectorAll('.kt-canvas text')].map(el => el.textContent)).toEqual(['离散数学'])
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：命题逻辑' }))
  expect(props.onNote).toHaveBeenCalledWith('c', 'b', section)
})

it('keeps zoom controls available and changes camera scale', async () => {
  const onViewChange = vi.fn()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  render(<KnowledgeTreeScene {...props} onViewChange={onViewChange} />)
  const before = screen.getByLabelText('知识树缩放').textContent
  fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
  await waitFor(() => expect(screen.getByLabelText('知识树缩放').textContent).not.toBe(before))
  vi.restoreAllMocks()
})

it('reframes an old row-layout camera once and records the new layout version', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const onViewChange = vi.fn()
  render(<KnowledgeTreeScene {...props} initialView={{ camera: { x: 10000, y: 10000, k: .7 }, viewport: { width: 1100, height: 720 }, slots: {} }} onViewChange={onViewChange} />)
  await waitFor(() => {
    const saved = onViewChange.mock.lastCall![0]
    expect(saved.layoutVersion).toBe(FOREST_LAYOUT_VERSION)
    expect(saved.camera.x).not.toBe(10000)
    expect(saved.camera.y).not.toBe(10000)
  })
  vi.restoreAllMocks()
})

it('keeps long course captions inside their own slot without covering a neighbouring course', () => {
  const grouped = Array.from({ length: 2 }, (_, index) => ({ ...course, course_id: `long-${index}`, name: `${index}${'知识森林'.repeat(30)}`.slice(0, 120), position: index }))
  const { container } = render(<KnowledgeTreeScene {...props} courses={grouped} trees={[]} initialView={{ layoutVersion: FOREST_LAYOUT_VERSION, camera: { x: 0, y: 0, k: .5 }, viewport: { width: 1100, height: 720 }, slots: {} }} />)
  const captions = [...container.querySelectorAll('.kt-forest-botanical')].map((element, index) => {
    const [center] = element.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    const action = screen.getByRole('button', { name: `课程菜单：${grouped[index].name}` })
    const target = action.querySelector('rect')!
    const left = center + Number(target.getAttribute('x'))
    const right = left + Number(target.getAttribute('width'))
    expect(action.querySelector('title')!.textContent).toContain(grouped[index].name)
    expect(action.querySelector('text')!.textContent!.length).toBeLessThan(grouped[index].name.length)
    expect(right - left).toBeLessThanOrEqual(580)
    return { center, left, right }
  })
  expect(captions[0].right).toBeLessThan(captions[1].left)
  expect(captions[0].right).toBeLessThan(captions[1].center)
})

it('frames a grounded three-tree grove with root-attached stones and all three AI connection sides', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const onViewChange = vi.fn()
  const grouped = Array.from({ length: 3 }, (_, index) => ({ ...course, course_id: `grove-${index}`, name: `课程${index}`, position: index }))
  const directories = grouped.map((row, index) => ({ course_id: row.course_id, notebooks: [{ ...book, id: `grove-book-${index}`, course_id: row.course_id, chapters: [{ ...book.chapters[0], sections: [{ ...section, id: `grove-note-${index}`, notebook_id: `grove-book-${index}` }] }] }] }))
  const edge = { id: 'grove-edge', source_course_id: grouped[0].course_id, target_course_id: grouped[2].course_id, source_block_id: 'grove-note-0', target_block_id: 'grove-note-2', source_title: '起点', target_title: '终点', status: 'confirmed', origin: 'ai', stale: false } as TreeRelation
  const { container } = render(<KnowledgeTreeScene {...props} courses={grouped} trees={directories} relations={[edge]} onViewChange={onViewChange} />)
  const roots = [...container.querySelectorAll('.kt-forest-botanical')].map(element => {
    const [x, y] = element.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    const [, offset] = element.querySelector('.kt-forest-course-info')!.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    return { x, y, caption: y + offset }
  })
  expect(roots[1].y).toBeLessThan(Math.min(roots[0].y, roots[2].y))
  expect(Math.max(...roots.map(root => root.y)) - Math.min(...roots.map(root => root.y))).toBeLessThanOrEqual(120)
  for (const root of roots) expect(root.caption - root.y).toBeLessThanOrEqual(50)
  expect(container.querySelector('[data-vine-members="grove-edge"]')).toBeTruthy()
  await waitFor(() => {
    const camera = onViewChange.mock.lastCall![0].camera
    for (const root of roots) {
      expect((root.x - 290) * camera.k + camera.x).toBeGreaterThanOrEqual(0)
      expect((root.x + 290) * camera.k + camera.x).toBeLessThanOrEqual(1100)
      expect((root.caption + 170) * camera.k + camera.y).toBeLessThanOrEqual(720)
    }
  })
  vi.restoreAllMocks()
})

it('uses the course caption to enter an operable detail view without a duplicate overview strip', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const grouped = Array.from({ length: 3 }, (_, index) => ({ ...course, course_id: `focus-${index}`, name: `课程${index}`, position: index }))
  const directories = grouped.map((row, index) => ({ course_id: row.course_id, notebooks: [{ ...book, id: `focus-book-${index}`, course_id: row.course_id, chapters: [{ ...book.chapters[0], sections: [{ ...section, id: `focus-note-${index}`, notebook_id: `focus-book-${index}` }] }] }] }))
  render(<KnowledgeTreeScene {...props} courses={grouped} trees={directories} />)
  fireEvent.click(screen.getByRole('button', { name: '适应全部课程' }))
  const focus = await screen.findByRole('button', { name: '聚焦课程：课程1' })
  expect(document.querySelector('.kt-overview-controls')).toBeNull()
  fireEvent.keyDown(focus, { key: 'Enter' })
  await screen.findByRole('button', { name: '课程菜单：课程1' })
  expect(Number.parseInt(screen.getByLabelText('知识树缩放').textContent!)).toBeGreaterThanOrEqual(50)
  expect(screen.getAllByRole('button', { name: '打开知识点：命题逻辑' })).toHaveLength(3)
  vi.restoreAllMocks()
})

it('reframes a different relation sharing the same two real notes after a reader pans', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const otherCourse = { ...course, course_id: 'other', name: '数字逻辑' }
  const otherNote = { ...section, id: 'other-note', notebook_id: 'other-book' }
  const otherBook = { ...book, id: 'other-book', course_id: 'other', chapters: [{ ...book.chapters[0], sections: [otherNote] }] }
  const relation: TreeRelation = { id: 'r1', source_course_id: 'c', target_course_id: 'other', source_block_id: section.id, target_block_id: otherNote.id, source_title: section.title, target_title: otherNote.title, source_course_name: course.name, target_course_name: otherCourse.name, relation_type: 'related', reason: '真实联系', status: 'confirmed', origin: 'ai', activation_mode: 'automatic', evidence_fingerprint: null, source_revision: 1, target_revision: 1, stale: false, source_ref_ids: [], target_ref_ids: [] }
  const shared = { ...props, courses: [course, otherCourse], trees: [...props.trees, { course_id: 'other', notebooks: [otherBook] }], relations: [relation, { ...relation, id: 'r2' }] }
  const view = render(<KnowledgeTreeScene {...shared} selectedRelationId="r1" />)
  await waitFor(() => expect(view.container.querySelector('.vine-leaf.is-selected')?.getAttribute('data-relation-id')).toBe('r1'))
  fireEvent.click(screen.getByRole('button', { name: '向右浏览课程' }))
  const moved = view.container.querySelector('.kt-canvas > g')!.getAttribute('transform')
  view.rerender(<KnowledgeTreeScene {...shared} selectedRelationId="r2" />)
  await waitFor(() => expect(view.container.querySelector('.kt-canvas > g')!.getAttribute('transform')).not.toBe(moved))
  vi.restoreAllMocks()
})

function inside(point: { x: number; y: number }, points: string) {
  const polygon = points.trim().split(/\s+/).map(pair => pair.split(',').map(Number))
  let result = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [x, y] = polygon[i], [px, py] = polygon[j]
    if ((y > point.y) !== (py > point.y) && point.x < (px - x) * (point.y - y) / (py - y) + x) result = !result
  }
  return result
}

it.each([4, 6])('gives every knowledge leaf an exclusive target with %i notebooks', count => {
  const books = Array.from({ length: count }, (_, index) => ({ ...book, id: `book-${index}`, course_id: 'course-a', tree_slot: index, chapters: [{ ...book.chapters[0], sections: Array.from({ length: 6 }, (_, slot) => ({ ...section, id: `b${index}-n${slot}`, notebook_id: `book-${index}`, tree_slot: slot })) }] }))
  const denseCourse = { ...course, course_id: 'course-a' }
  const canopy = forestCanopyGeometry('course-a', books.map(notebookGeometry), new Set(), '')
  const view = render(<KnowledgeTreeScene {...props} courses={[denseCourse]} trees={[{ course_id: 'course-a', notebooks: books }]} />)
  const leaves = canopy.items.flatMap(item => item.leaves)
  for (const leaf of leaves) {
    const radians = leaf.angle * Math.PI / 180
    const center = { x: leaf.x + Math.sin(radians) * 30, y: leaf.y - Math.cos(radians) * 30 }
    const target = view.container.querySelector(`[data-leaf-hit-note-id="${leaf.section.id}"]`)!
    const clip = target.parentElement!.getAttribute('clip-path')
    expect(clip, `unpartitioned target for ${leaf.section.id}`).toBeTruthy()
    const clipId = clip!.slice(5, -1)
    const polygon = view.container.querySelector(`[id="${clipId}"] polygon`)!.getAttribute('points')!
    expect(inside(center, polygon), `own center for ${leaf.section.id}`).toBe(true)
    for (const other of leaves.filter(other => other !== leaf)) {
      const angle = other.angle * Math.PI / 180
      expect(inside({ x: other.x + Math.sin(angle) * 30, y: other.y - Math.cos(angle) * 30 }, polygon), `${other.section.id} covered by ${leaf.section.id}`).toBe(false)
    }
  }
})
