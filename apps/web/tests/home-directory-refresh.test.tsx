import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'
import { ForestPage } from '../src/pages/ForestPage'

vi.mock('../src/api', () => ({ api: {
  getForest: vi.fn(), getCourseTree: vi.fn(), getForestRelations: vi.fn().mockResolvedValue([]),
  getLatestForestJob: vi.fn().mockResolvedValue(null), getForestJob: vi.fn(),
} }))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); sessionStorage.clear() })

test.each(['home', 'forest'])('%s refreshes an already loaded tree after an edit in another window', async mode => {
  let updated = false
  const course = { id: 'c', name: '课程', created_at: '2026-10-25' }
  vi.mocked(api.getForest).mockResolvedValue({ courses: [{ course_id: 'c', name: '课程',
    learning_state: 'learning', position: 0, level: 'foundation', semester: 1,
    prerequisites: [], revision: 1, note_count: 1, material_count: 1 }] })
  vi.mocked(api.getCourseTree).mockImplementation(async () => ({ course_id: 'c', notebooks: [{
    id: 'book', course_id: 'c', title: '笔记本', tree_slot: 0, order_revision: 0,
    chapters: [{ id: 'm', title: '讲次', status: 'completed', deleted_at: null, chapter_order: 0,
      sections: [{ id: 'note', block_id: 'note', notebook_id: 'book', title: updated ? '改名后的知识点' : '原知识点',
        tree_slot: 0, material_id: 'm' }] }], historical_sections: [], removed_chapters: [],
  }] }) as never)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  render(<MemoryRouter initialEntries={[mode === 'home' ? '/' : '/forest']}>
    <WorkspaceProvider value={{ courses: [course], coursesLoading: false, refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}>
      {mode === 'home' ? <HomePage /> : <ForestPage />}
    </WorkspaceProvider>
  </MemoryRouter>)
  await screen.findByRole('button', { name: '打开知识点：原知识点' })
  updated = true
  fireEvent.focus(window)
  await screen.findByRole('button', { name: '打开知识点：改名后的知识点' })
  expect(screen.queryByRole('button', { name: '打开知识点：原知识点' })).toBeNull()
})

test('a focus refresh queued behind an older read eventually shows the newer directory', async () => {
  const { useTreeDirectories } = await import('../src/features/forest/useTreeDirectories')
  const { renderHook } = await import('@testing-library/react')
  let finish!: (value: unknown) => void
  vi.mocked(api.getCourseTree).mockImplementationOnce(() => new Promise(resolve => { finish = resolve as never }))
    .mockResolvedValue({ course_id: 'c', notebooks: [{ id: 'new-book', course_id: 'c', title: '新笔记本',
      tree_slot: 0, order_revision: 0, chapters: [], historical_sections: [], removed_chapters: [] }] } as never)
  const { result } = renderHook(() => useTreeDirectories())
  act(() => result.current.watch(['c']))
  act(() => { void result.current.refresh(['c']) })
  await act(async () => { finish({ course_id: 'c', notebooks: [] }) })
  await waitFor(() => expect(result.current.trees[0]?.notebooks[0]?.id).toBe('new-book'))
})

test('another focus during the queued request still triggers a final fresh directory read', async () => {
  const { useTreeDirectories } = await import('../src/features/forest/useTreeDirectories')
  const { renderHook } = await import('@testing-library/react')
  let first!: (value: unknown) => void, second!: (value: unknown) => void
  const directory = (id: string) => ({ course_id: 'c', notebooks: [{ id, chapters: [], historical_sections: [], removed_chapters: [] }] })
  vi.mocked(api.getCourseTree)
    .mockImplementationOnce(() => new Promise(resolve => { first = resolve as never }))
    .mockImplementationOnce(() => new Promise(resolve => { second = resolve as never }))
    .mockResolvedValue(directory('newest') as never)
  const { result } = renderHook(() => useTreeDirectories())
  act(() => result.current.watch(['c']))
  act(() => { void result.current.refresh(['c']) })
  await act(async () => { first(directory('old')) })
  act(() => { void result.current.refresh(['c']) })
  await act(async () => { second(directory('middle')) })
  await waitFor(() => expect(result.current.trees[0]?.notebooks[0]?.id).toBe('newest'))
})

test('older relation and job responses cannot replace a newer focus refresh', async () => {
  const { useNotebookRelations } = await import('../src/features/forest/useNotebookRelations')
  const { renderHook } = await import('@testing-library/react')
  vi.mocked(api.getForestRelations).mockResolvedValue([])
  vi.mocked(api.getLatestForestJob).mockResolvedValue(null)
  const { result } = renderHook(() => useNotebookRelations([], 0, 'c', vi.fn()))
  await act(async () => { await Promise.resolve() })
  let oldRelations!: (value: unknown) => void, oldJob!: (value: unknown) => void
  vi.mocked(api.getForestRelations)
    .mockImplementationOnce(() => new Promise(resolve => { oldRelations = resolve as never }))
    .mockResolvedValueOnce([{ id: 'new-relation' }] as never)
  vi.mocked(api.getLatestForestJob)
    .mockImplementationOnce(() => new Promise(resolve => { oldJob = resolve as never }))
    .mockResolvedValueOnce({ id: 'new-job', status: 'completed' } as never)
  act(() => { void result.current.refresh(); void result.current.discoverJobs() })
  await act(async () => { await result.current.refresh(); await result.current.discoverJobs() })
  await act(async () => {
    oldRelations([{ id: 'old-relation' }]); oldJob({ id: 'old-job', status: 'failed' })
  })
  expect(result.current.records[0]?.id).toBe('new-relation')
  expect(result.current.jobs.c.id).toBe('new-job')
})
