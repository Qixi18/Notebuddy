import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { KnowledgeTreeScene } from '../src/features/forest/KnowledgeTreeScene'
import { notebookGeometry, overviewLeaves, sceneInitialCamera } from '../src/features/forest/treeGeometry'
import type { NotebookRead, SectionRead } from '../src/types'
import type { ForestCourse } from '../src/features/forest/types'

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
})
afterEach(async () => { cleanup(); await new Promise(resolve => window.setTimeout(resolve, 0)); vi.unstubAllGlobals() })
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
describe('persistent botanical slots', () => {
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
})
