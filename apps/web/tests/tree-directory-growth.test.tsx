import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'
import { ForestPage } from '../src/pages/ForestPage'
vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn().mockResolvedValue([]), getCourseTree: vi.fn(), getLatestForestJob: vi.fn().mockResolvedValue(null) } }))
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks(); sessionStorage.clear() })
test.each(['home', 'forest'])('%s grows a real generated Note in the same scene and stops polling when its pending material completes', async mode => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  let generated = false
  const course = { id: 'c', name: '课程', created_at: '2026-10-15', last_opened_at: null }
  const section = { id: 'real-generated-note', notebook_id: 'book', tree_slot: 0, material_id: 'material', title: '成功生成的知识点' }
  vi.mocked(api.getForest).mockResolvedValue({ courses: [{ course_id: 'c', name: '课程', semester: 1, position: 0, level: 'foundation', learning_state: 'learning', prerequisites: [], revision: 0 }] } as never)
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [{ id: 'book', course_id: id, title: '笔记本', tree_slot: 0, order_revision: 0, chapters: [{ id: 'material', title: '等待处理的第一讲', status: generated ? 'completed' : 'pending', sections: generated ? [section] : [] }], historical_sections: [], removed_chapters: [] }] }) as never)
  const { container } = render(<MemoryRouter initialEntries={[mode === 'home' ? '/' : '/forest']}><WorkspaceProvider value={{ courses: [course], coursesLoading: false, refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}>{mode === 'home' ? <HomePage /> : <ForestPage />}</WorkspaceProvider></MemoryRouter>)
  await screen.findByRole('button', { name: '续读笔记本：笔记本' })
  expect(container.querySelector('[data-note-id="real-generated-note"]')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
  const camera = container.querySelector('.kt-canvas > g')!.getAttribute('transform')
  const scene = container.querySelector('.knowledge-tree-scene')
  generated = true // The persistent material job has now committed the real directory.
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  const leaf = await screen.findByRole('button', { name: '打开知识点：成功生成的知识点' })
  expect(leaf.closest('[data-note-id]')?.getAttribute('data-note-id')).toBe('real-generated-note')
  expect(leaf.closest('[data-notebook-id]')?.getAttribute('data-notebook-id')).toBe('book')
  expect(container.querySelector('.knowledge-tree-scene')).toBe(scene)
  expect(container.querySelector('.kt-canvas > g')!.getAttribute('transform')).toBe(camera)
  const finishedCalls = vi.mocked(api.getCourseTree).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  await waitFor(() => expect(vi.mocked(api.getCourseTree).mock.calls.length).toBe(finishedCalls))
})
