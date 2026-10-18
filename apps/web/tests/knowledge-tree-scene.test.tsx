import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeTreeScene } from '../src/features/tree/KnowledgeTreeScene'
import { notebookGeometry, overviewLeaves, sceneInitialCamera } from '../src/features/tree/treeGeometry'
import type { NotebookRead, SectionRead } from '../src/types'
import type { CrossCourseRelation, ForestCourse } from '../src/features/forest/types'

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
})
afterEach(async () => { cleanup(); await new Promise(resolve => window.setTimeout(resolve, 0)); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const course: ForestCourse = { course_id: 'course', name: '离散数学', semester: 1, level: 'foundation', learning_state: 'learning', position: 0, revision: 1, note_count: 200, material_count: 1, prerequisites: [] }
function section(slot: number): SectionRead {
  return { id: `note-${slot}`, notebook_id: 'book', tree_slot: slot, knowledge_node_id: `node-${slot}`, material_id: 'chapter', section_key: String(slot), section_order: slot, title: `知识点${slot}`, revision_number: 1, user_locked: false, updated_at: '' }
}
function book(count = 3, slot = 0): NotebookRead {
  return { id: 'book', course_id: 'course', title: '数学笔记', tree_slot: slot, order_revision: 0, chapters: [{ id: 'chapter', title: '第一讲', chapter_order: 0, status: 'completed', deleted_at: null, sections: Array.from({ length: count }, (_, i) => section(i)) }], historical_sections: [], removed_chapters: [] }
}
function mount(count = 3, extra = {}) {
  const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
  render(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [book(count)] }]} {...callbacks} {...extra} />)
  return callbacks
}
it('frames courses that arrive after mount and their first lazy directories', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
  const { container, rerender } = render(<KnowledgeTreeScene courses={[]} trees={[]} {...callbacks} />)
  rerender(<KnowledgeTreeScene courses={[course]} trees={[]} {...callbacks} />)
  await waitFor(() => expect(container.querySelector('[data-course-id="course"]')).toBeTruthy())
  const before = container.querySelector('.kt-canvas > g')!.getAttribute('transform')
  const manyBooks = Array.from({ length: 6 }, (_, slot) => ({ ...book(6, slot), id: `book-${slot}`, chapters: book(6, slot).chapters.map(ch => ({ ...ch, sections: ch.sections.map(section => ({ ...section, notebook_id: `book-${slot}`, id: `${slot}-${section.id}` })) })) }))
  rerender(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: manyBooks }]} {...callbacks} />)
  await waitFor(() => expect(container.querySelector('.kt-canvas > g')!.getAttribute('transform')).not.toBe(before))
})
it('lazy directories preserve a camera the reader already moved', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
  const { container, rerender } = render(<KnowledgeTreeScene courses={[course]} trees={[]} {...callbacks} />)
  fireEvent.click(screen.getByRole('button', { name: '向右浏览课程' }))
  const before = container.querySelector('.kt-canvas > g')!.getAttribute('transform')
  rerender(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [book(200)] }]} {...callbacks} />)
  await waitFor(() => expect(container.querySelector('[data-note-id="note-0"]')).toBeTruthy())
  expect(container.querySelector('.kt-canvas > g')!.getAttribute('transform')).toBe(before)
})
describe('persistent botanical slots', () => {
  it('adds one independently growing book branch without replacing or moving existing books and Notes', () => {
    const first = book(3)
    const second = { ...book(0, 1), id: 'new-book', title: '新增的笔记本' }
    const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
    const props = { courses: [course], ...callbacks }
    const view = render(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: [first] }]} />)
    const oldBranch = view.container.querySelector('.kt-branch[data-notebook-id="book"]')
    const oldLeaf = view.container.querySelector('[data-note-id="note-1"]')
    const leafPosition = oldLeaf?.querySelector('[data-leaf-paint]')?.getAttribute('transform')
    const oldGeometry = notebookGeometry(first)
    expect(view.container.querySelector('.kt-branch-growth')).toBeNull()
    view.rerender(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: [first, second] }]} />)
    expect(screen.getByRole('button', { name: '续读笔记本：新增的笔记本' })).toBeTruthy()
    expect(view.container.querySelector('.kt-branch[data-notebook-id="book"]')).toBe(oldBranch)
    expect(view.container.querySelector('[data-note-id="note-1"]')).toBe(oldLeaf)
    expect(oldLeaf?.querySelector('[data-leaf-paint]')?.getAttribute('transform')).toBe(leafPosition)
    expect(notebookGeometry(first)).toEqual(oldGeometry)
    const growth = view.container.querySelectorAll('.kt-branch-growth')
    expect(growth).toHaveLength(1)
    expect(growth[0].closest('[data-wood-notebook-id]')?.getAttribute('data-wood-notebook-id')).toBe('new-book')
    fireEvent.keyDown(screen.getByRole('button', { name: '续读笔记本：新增的笔记本' }), { key: 'Enter' })
    expect(callbacks.onNotebook).toHaveBeenCalledExactlyOnceWith('course', 'new-book')
    // A refreshed copy of the directory must not replay old branch growth.
    view.rerender(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: structuredClone([first, second]) }]} />)
    expect(view.container.querySelector('.kt-branch-growth')).toBeNull()
    view.unmount()
    const reloaded = render(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: [first, second] }]} />)
    expect(reloaded.container.querySelector('.kt-branch-growth')).toBeNull()
  })
  it('does not replay branch growth for the first lazy directory or exceed the six-book overview', () => {
    const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
    const initialBooks = Array.from({ length: 6 }, (_, slot) => ({ ...book(0, slot), id: `book-${slot}`, title: `笔记本${slot}` }))
    const props = { courses: [course], ...callbacks }
    const view = render(<KnowledgeTreeScene {...props} trees={[]} />)
    view.rerender(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: initialBooks }]} />)
    expect(view.container.querySelector('.kt-branch-growth')).toBeNull()
    const seventh = { ...book(0, 6), id: 'seventh', title: '第七本笔记本' }
    view.rerender(<KnowledgeTreeScene {...props} trees={[{ course_id: 'course', notebooks: [...initialBooks, seventh] }]} />)
    expect(view.container.querySelectorAll('.kt-branch')).toHaveLength(6)
    fireEvent.click(screen.getByRole('button', { name: '展开离散数学的全部7本笔记本' }))
    fireEvent.click(screen.getByRole('button', { name: '第七本笔记本 · 继续阅读' }))
    expect(callbacks.onNotebook).toHaveBeenCalledExactlyOnceWith('course', 'seventh')
  })
  it('compares against the saved course book baseline after returning from the upload route', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
    const onViewChange = vi.fn()
    const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
    const first = book(3)
    const view = render(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [first] }]} onViewChange={onViewChange} {...callbacks} />)
    fireEvent.click(screen.getByRole('button', { name: '课程菜单：离散数学' }))
    await waitFor(() => expect(onViewChange).toHaveBeenCalled())
    const saved = onViewChange.mock.lastCall![0]
    view.unmount() // Root menu creation navigates to the separate upload route.
    const second = { ...book(0, 1), id: 'created-while-away', title: '返回时的新笔记本' }
    const returned = render(<KnowledgeTreeScene courses={[course]} trees={[]} initialView={saved} onViewChange={onViewChange} {...callbacks} />)
    returned.rerender(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [first, second] }]} initialView={saved} onViewChange={onViewChange} {...callbacks} />)
    const growth = returned.container.querySelectorAll('.kt-branch-growth')
    expect(growth).toHaveLength(1)
    expect(growth[0].closest('[data-wood-notebook-id]')?.getAttribute('data-wood-notebook-id')).toBe(second.id)
    fireEvent.click(screen.getByRole('button', { name: '课程菜单：离散数学' }))
    expect(onViewChange.mock.lastCall![0].knownNotebookIds.course).toEqual(['book', second.id])
  })
  it('shows the new branch immediately without growth motion when reduced motion is requested', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    const callbacks = { onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn() }
    const first = book(3), second = { ...book(0, 1), id: 'new', title: '新增本' }
    const view = render(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [first] }]} {...callbacks} />)
    view.rerender(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [first, second] }]} {...callbacks} />)
    expect(screen.getByRole('button', { name: '续读笔记本：新增本' })).toBeTruthy()
    expect(view.container.querySelector('.kt-branch-growth')).toBeNull()
  })
  it('preserves book and Note positions on insertion, reorder, removal and restoration', () => {
    const before = notebookGeometry(book(3))
    expect(before.leaves).toHaveLength(3)
    const next = book(4)
    next.chapters[0].sections.reverse()
    const after = notebookGeometry(next)
    for (const leaf of before.leaves) expect(after.leaves.find(item => item.section.id === leaf.section.id)).toEqual(leaf)
    next.chapters[0].sections = next.chapters[0].sections.filter(item => item.tree_slot !== 1)
    expect(notebookGeometry(next).leaves.find(item => item.section.id === 'note-2')).toEqual(before.leaves[2])
    next.historical_sections.push(section(1))
    expect(notebookGeometry(next).leaves.find(item => item.section.id === 'note-1')?.x).toBe(before.leaves[1].x)
    expect(notebookGeometry(book(3, 2)).anchor).toEqual(notebookGeometry(book(4, 2)).anchor)
  })
  it('frames three, two or one tree from actual available canvas width', () => {
    expect(sceneInitialCamera(3, 1700, 850).visibleCount).toBe(3)
    expect(sceneInitialCamera(3, 1100, 750).visibleCount).toBe(2)
    expect(sceneInitialCamera(3, 390, 720).visibleCount).toBe(1)
  })
  it('reveals distant relation endpoints in a compact lens without moving overview leaves', () => {
    const geometry = notebookGeometry(book(200))
    const overview = overviewLeaves(geometry, new Set(), '')
    const pinned = overviewLeaves(geometry, new Set(['note-199']), '')
    expect(pinned.slice(0, 6)).toEqual(overview)
    expect(pinned.find(leaf => leaf.section.id === 'note-199')!.y).toBeGreaterThan(-1100)
  })
})
describe('tree actions', () => {
  it('routes root, notebook and exact leaf separately using real IDs', () => {
    const c = mount()
    fireEvent.click(screen.getByRole('button', { name: '课程菜单：离散数学' }))
    fireEvent.click(screen.getByRole('button', { name: '续读笔记本：数学笔记' }))
    fireEvent.click(screen.getByRole('button', { name: '打开知识点：知识点1' }))
    expect(c.onRoot).toHaveBeenCalledExactlyOnceWith('course')
    expect(c.onNotebook).toHaveBeenCalledExactlyOnceWith('course', 'book')
    expect(c.onNote).toHaveBeenCalledExactlyOnceWith('course', 'book', section(1))
  })
  it('does not turn a drag over six pixels into a leaf click', () => {
    const c = mount()
    const leaf = screen.getByRole('button', { name: '打开知识点：知识点1' })
    for (const [type, x] of [['mouseDown', 10], ['mouseMove', 18], ['mouseUp', 18]] as const) {
      const event = createEvent[type](leaf, { clientX: x, clientY: 10 })
      Object.defineProperty(event, 'view', { value: window })
      fireEvent(leaf, event)
    }
    fireEvent.click(leaf)
    expect(c.onNote).not.toHaveBeenCalled()
  })
  it('allows all 200 real sections through dense expansion and closes with focus restored', () => {
    const c = mount(200)
    const expand = screen.getByRole('button', { name: '展开数学笔记的全部200个知识点' })
    fireEvent.click(expand)
    fireEvent.click(screen.getByRole('button', { name: '第一讲 · 知识点199' }))
    expect(c.onNote).toHaveBeenCalledExactlyOnceWith('course', 'book', section(199))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(expand)
  })
  it('supports keyboard activation and exposes pinned search endpoints outside overview', () => {
    const c = mount(200, { pinnedNoteIds: ['note-199'] })
    fireEvent.keyDown(screen.getByRole('button', { name: '打开知识点：知识点199' }), { key: 'Enter' })
    expect(c.onNote).toHaveBeenCalledExactlyOnceWith('course', 'book', section(199))
  })
  it('draws no knowledge leaves for an empty planned course', () => {
    render(<KnowledgeTreeScene courses={[course]} trees={[{ course_id: 'course', notebooks: [] }]} onRoot={vi.fn()} onNotebook={vi.fn()} onNote={vi.fn()} onRelation={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /打开知识点/ })).toBeNull()
  })
  it('restores camera using measured container dimensions and returns its viewport', async () => {
    const dimensions = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 900, bottom: 600, width: 900, height: 600, toJSON: () => ({}) })
    const onViewChange = vi.fn()
    mount(3, { initialView: { camera: { x: -500, y: -100, k: 1 }, viewport: { width: 1200, height: 800 }, slots: {} }, onViewChange })
    await waitFor(() => expect(onViewChange).toHaveBeenLastCalledWith(expect.objectContaining({ camera: { x: -650, y: -200, k: 1 }, viewport: { width: 900, height: 600 } })))
    dimensions.mockRestore()
  })
  it('restores density expansion after lazy directory load and does not reopen after closing', async () => {
    const dimensions = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 1000, bottom: 700, width: 1000, height: 700, toJSON: () => ({}) })
    const onViewChange = vi.fn()
    const props = { courses: [course], trees: [{ course_id: 'course', notebooks: [book(200)] }], onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn(), onViewChange }
    const first = render(<KnowledgeTreeScene {...props} />)
    fireEvent.click(screen.getByRole('button', { name: '展开数学笔记的全部200个知识点' }))
    await waitFor(() => expect(onViewChange).toHaveBeenLastCalledWith(expect.objectContaining({ contents: { courseId: 'course', notebookId: 'book' } })))
    const saved = onViewChange.mock.lastCall![0]
    first.unmount()
    const restored = render(<KnowledgeTreeScene {...props} trees={[]} initialView={saved} />)
    expect(screen.queryByRole('dialog')).toBeNull()
    restored.rerender(<KnowledgeTreeScene {...props} initialView={saved} />)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    restored.rerender(<KnowledgeTreeScene {...props} initialView={saved} search="知识" />)
    expect(screen.queryByRole('dialog')).toBeNull()
    dimensions.mockRestore()
  })
  it('restores a revealed dense leaf from serializable view state', () => {
    mount(200, { initialView: { camera: { x: 0, y: 0, k: 1 }, viewport: { width: 1000, height: 700 }, slots: {}, revealedNoteId: 'note-199' } })
    expect(screen.getByRole('button', { name: '打开知识点：知识点199' })).toBeTruthy()
  })
  it('frames both selected vine endpoints after the second course directory arrives', async () => {
    const dimensions = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 1100, bottom: 750, width: 1100, height: 750, toJSON: () => ({}) })
    const courses = Array.from({ length: 9 }, (_, index) => ({ ...course, course_id: `course-${index}`, position: index }))
    const a = book(1); a.course_id = 'course-0'
    const b = book(1); b.course_id = 'course-8'; b.id = 'target-book'; b.chapters[0].sections = [{ ...section(0), id: 'target-note', notebook_id: b.id }]
    const relation: CrossCourseRelation = { id: 'vine', source_course_id: a.course_id, target_course_id: b.course_id, source_note_id: 'note-0', target_note_id: 'target-note', source_title: '知识点0', target_title: '目标知识点', source_course_name: '甲', target_course_name: '乙', relation_type: 'related', reason: '课程证据', status: 'confirmed', origin: 'ai', source_revision: 1, target_revision: 1, stale: false, source_ref_ids: [], target_ref_ids: [] }
    const onViewChange = vi.fn()
    const onVisibleCourseIdsChange = vi.fn()
    const props = { courses, trees: [{ course_id: a.course_id, notebooks: [a] }], relations: [relation], selectedRelationId: 'vine', onRoot: vi.fn(), onNotebook: vi.fn(), onNote: vi.fn(), onRelation: vi.fn(), onViewChange, onVisibleCourseIdsChange }
    const instance = render(<KnowledgeTreeScene {...props} />)
    await waitFor(() => expect(onViewChange).toHaveBeenCalled())
    expect(onVisibleCourseIdsChange.mock.lastCall![0]).toEqual(expect.arrayContaining([a.course_id, b.course_id]))
    instance.rerender(<KnowledgeTreeScene {...props} trees={[...props.trees, { course_id: b.course_id, notebooks: [b] }]} />)
    await waitFor(() => {
      const current = onViewChange.mock.lastCall![0].camera
      for (const [courseId, notebook] of [[a.course_id, a], [b.course_id, b]] as const) {
        const element = instance.container.querySelector(`[data-course-id="${courseId}"]`)!
        const [x, y] = element.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
        const leaf = notebookGeometry(notebook).leaves[0]
        expect((x + leaf.x) * current.k + current.x).toBeGreaterThan(0)
        expect((x + leaf.x) * current.k + current.x).toBeLessThan(1100)
        expect((y + leaf.y - 25) * current.k + current.y).toBeGreaterThan(0)
        expect((y + leaf.y - 25) * current.k + current.y).toBeLessThan(750)
      }
    })
    instance.unmount()
    const savedCamera = { x: -125, y: -80, k: .7 }
    const initialView = { camera: savedCamera, viewport: { width: 1100, height: 750 }, slots: {} }
    const restored = render(<KnowledgeTreeScene {...props} initialView={initialView} />)
    await waitFor(() => expect(onViewChange.mock.lastCall![0].camera).toEqual(savedCamera))
    restored.rerender(<KnowledgeTreeScene {...props} initialView={initialView} trees={[...props.trees, { course_id: b.course_id, notebooks: [b] }]} />)
    await waitFor(() => expect(onViewChange.mock.lastCall![0].camera).toEqual(savedCamera))
    dimensions.mockRestore()
  })
})
