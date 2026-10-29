import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { HomeCourseGarden } from '../src/features/home/HomeCourseGarden'
import { growthLedger } from '../src/features/tree/growth/ledger'
import { TreeVines } from '../src/features/tree/TreeVines'
import type { CourseTree } from '../src/types'
import type { TreeRelation, ForestCourse } from '../src/features/forest/types'
import { sceneBlockId } from '../src/features/forest/notebookRelations'

const course = { course_id: 'growth-course', name: '生长课程', learning_state: 'learning', note_count: 1 } as ForestCourse
const book = (id: string) => ({ id, course_id: course.course_id, title: id, tree_slot: id === 'old-book' ? 0 : 1, chapters: [{ id: 'm', title: '第一讲', status: 'completed', sections: [{ id: `note-${id}`, block_id: `note-${id}`, title: `知识-${id}`, notebook_id: id, material_id: 'm', tree_slot: 0 }] }], historical_sections: [], removed_chapters: [] })
const tree = (added = false) => [{ course_id: course.course_id, notebooks: [book('old-book'), ...(added ? [book('new-book')] : [])] }] as CourseTree[]
const actions = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn() }
beforeEach(() => {
  sessionStorage.clear()
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 600, bottom: 600, width: 600, height: 600, toJSON() {} })
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: -250, y: -700, width: 500, height: 730 }) })
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: () => ({ finished: new Promise<Animation>(() => {}), cancel() {} }) })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals(); delete (Element.prototype as Partial<Element>).animate; sessionStorage.clear() })
test('home animates a real new branch once, keeps hit positions, and focus completes it before opening', async () => {
  const view = render(<StrictMode><HomeCourseGarden courses={[course]} trees={tree()} {...actions} /></StrictMode>)
  expect(view.container.querySelector('[data-growth-defs]')).toBeNull()
  view.rerender(<StrictMode><HomeCourseGarden courses={[course]} trees={tree(true)} {...actions} /></StrictMode>)
  await waitFor(() => expect(view.container.querySelector('[data-growth-defs]')).not.toBeNull())
  const leaf = view.container.querySelector('[data-home-leaf-id="note-new-book"]')!
  const position = leaf.getAttribute('transform')
  fireEvent.focus(screen.getByRole('button', { name: '打开知识点：知识-new-book' }))
  expect(view.container.querySelector('[data-growth-defs]')).toBeNull()
  expect(leaf.getAttribute('transform')).toBe(position)
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识-new-book' }))
  expect(actions.onNote).toHaveBeenCalledExactlyOnceWith(course.course_id, 'new-book', expect.objectContaining({ id: 'note-new-book' }))
  view.unmount()
  const returned = render(<HomeCourseGarden courses={[course]} trees={tree(true)} {...actions} />)
  expect(returned.container.querySelector('[data-growth-defs]')).toBeNull()
})
test('a covered scene holds new course growth until its modal closes', async () => {
  growthLedger.observeCourses([])
  growthLedger.observeCourses([course.course_id])
  const modal = document.createElement('div'); modal.setAttribute('role', 'dialog'); document.body.append(modal)
  const view = render(<HomeCourseGarden courses={[course]} trees={tree()} {...actions} />)
  await new Promise(resolve => requestAnimationFrame(resolve))
  expect(view.container.querySelector('[data-growth-defs]')).toBeNull()
  expect(growthLedger.pending().some(e => e.kind === 'course')).toBe(true)
  modal.remove()
  await waitFor(() => expect(view.container.querySelector('[data-growth-defs]')).not.toBeNull())
})
test('a new relation grows its stem, adding to an existing stem only unfolds the new relation leaf', async () => {
  vi.mocked(Element.prototype.getBoundingClientRect).mockImplementation(function (this: Element) {
    const left = this.closest('[data-course-id="other-course"]') ? 650 : 0
    return { x: left, y: 0, top: 0, left, right: left + 600, bottom: 600, width: 600, height: 600, toJSON() {} }
  })
  const other = { ...course, course_id: 'other-course', name: '其他课程' }
  const relation = (id: string) => ({ id, source_course_id: course.course_id, target_course_id: other.course_id, source_notebook_id: 'old-book', target_notebook_id: 'other-book', source_block_id: sceneBlockId('old-book', 'note-old-book'), target_block_id: sceneBlockId('other-book', 'note-other-book'), source_title: '来源', target_title: '目标', status: 'confirmed', stale: false, origin: 'manual', relation_type: 'related', reason: '关系', created_at: '' }) as TreeRelation
  growthLedger.observeRelations([])
  const endpoints = new Map([[sceneBlockId('old-book', 'note-old-book'), { x: 20, y: 200 }], [sceneBlockId('other-book', 'note-other-book'), { x: 850, y: 200 }]])
  const scene = (relations: TreeRelation[]) => <svg><TreeVines relations={relations} endpoints={endpoints} zoom={1} viewKey="fixed" onRelation={() => {}} /></svg>
  const view = render(scene([]))
  growthLedger.observeRelations([relation('r1')])
  view.rerender(scene([relation('r1')]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull())
  fireEvent.focus(screen.getByRole('button', { name: /查看.*1条知识联系/ }))
  expect(view.container.querySelector('[data-growth-vine-path][mask]')).toBeNull()
  growthLedger.observeRelations([relation('r1'), relation('r2')])
  view.rerender(scene([relation('r1'), relation('r2')]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-relation-leaf="r2"][style]')).not.toBeNull())
  expect(view.container.querySelector('[data-growth-vine-path][mask]')).toBeNull()
  expect(view.container.querySelector('[data-growth-relation-leaf="r1"][style]')).toBeNull()
})
test('an old visible vine cannot consume a different offscreen new group', async () => {
  let offscreen = true
  vi.mocked(Element.prototype.getBoundingClientRect).mockImplementation(function (this: Element) {
    const left = offscreen && this.closest('[data-vine-members="off"], [data-relation-id="off"]') ? 5000 : 0
    return { x: left, y: 0, top: 0, left, right: left + 600, bottom: 600, width: 600, height: 600, toJSON() {} }
  })
  const row = (id: string) => ({ id, source_course_id: `${id}-a`, target_course_id: `${id}-b`, source_notebook_id: `${id}-book-a`, target_notebook_id: `${id}-book-b`, source_block_id: sceneBlockId(`${id}-book-a`, `${id}-n1`), target_block_id: sceneBlockId(`${id}-book-b`, `${id}-n2`), source_title: id, target_title: id, status: 'confirmed', stale: false, origin: 'manual', relation_type: 'related', reason: '关系', created_at: '' }) as TreeRelation
  const endpoints = new Map([[sceneBlockId('old-book-a', 'old-n1'), { x: 0, y: 200 }], [sceneBlockId('old-book-b', 'old-n2'), { x: 800, y: 200 }], [sceneBlockId('off-book-a', 'off-n1'), { x: 5000, y: 200 }], [sceneBlockId('off-book-b', 'off-n2'), { x: 5800, y: 200 }]])
  growthLedger.observeRelations([row('old')])
  const scene = (relations: TreeRelation[]) => <svg><TreeVines relations={relations} endpoints={endpoints} zoom={1} viewKey="fixed" onRelation={() => {}} /></svg>
  const view = render(scene([row('old')]))
  growthLedger.observeRelations([row('old'), row('off')])
  view.rerender(scene([row('old'), row('off')]))
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  expect(growthLedger.pending().map(e => e.id)).toEqual(['off'])
  expect(view.container.querySelector('[data-growth-defs]')).toBeNull()
  offscreen = false // The user pans the same scene; no new data response occurs.
  view.rerender(scene([row('old'), row('off')]))
  await waitFor(() => expect(view.container.querySelector('[data-growth-vine-path][mask]')).not.toBeNull())
  expect(growthLedger.pending()).toEqual([])
})
test('three new visible stems consume overflow statically instead of scheduling a second wave', async () => {
  const rows = ['one', 'two', 'three'].map(id => ({ id, source_course_id: `${id}-a`, target_course_id: `${id}-b`, source_notebook_id: `${id}-book-a`, target_notebook_id: `${id}-book-b`, source_block_id: sceneBlockId(`${id}-book-a`, `${id}-n1`), target_block_id: sceneBlockId(`${id}-book-b`, `${id}-n2`), source_title: id, target_title: id, status: 'confirmed', stale: false, origin: 'manual', relation_type: 'related', reason: '关系', created_at: '' })) as TreeRelation[]
  const endpoints = new Map(rows.flatMap((r, index) => [[r.source_block_id, { x: 10, y: 140 + index * 110 }], [r.target_block_id, { x: 850, y: 140 + index * 110 }]] as [string, { x: number; y: number }][]))
  growthLedger.observeRelations([])
  const scene = (relations: TreeRelation[]) => <svg><TreeVines relations={relations} endpoints={endpoints} zoom={1} viewKey="fixed" onRelation={() => {}} /></svg>
  const view = render(scene([]))
  growthLedger.observeRelations(rows)
  view.rerender(scene(rows))
  await waitFor(() => expect(view.container.querySelectorAll('[data-growth-vine-path][mask]')).toHaveLength(2))
  expect(growthLedger.pending()).toEqual([])
})
test('changing reduced-motion during playback finishes paint and leaves the knowledge point operable', async () => {
  let reduced = false, changed: (() => void) | undefined
  vi.stubGlobal('matchMedia', () => ({ get matches() { return reduced }, addEventListener: (_: string, fn: () => void) => { changed = fn }, removeEventListener() {} }))
  const view = render(<HomeCourseGarden courses={[course]} trees={tree()} {...actions} />)
  view.rerender(<HomeCourseGarden courses={[course]} trees={tree(true)} {...actions} />)
  await waitFor(() => expect(view.container.querySelector('[data-growth-defs]')).not.toBeNull())
  act(() => { reduced = true; changed?.() })
  await waitFor(() => expect(view.container.querySelector('[data-growth-defs]')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识-new-book' }))
  expect(actions.onNote).toHaveBeenCalledExactlyOnceWith(course.course_id, 'new-book', expect.objectContaining({ id: 'note-new-book' }))
})
