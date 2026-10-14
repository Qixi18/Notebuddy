import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
vi.mock('../src/features/conversation/useConversation', () => ({ useConversation: () => ({ busy: false }) }))
import { useWorkspaceState } from '../src/features/workspace/useWorkspaceState'
import { api } from '../src/api'

vi.mock('../src/features/assistant/useAssistantState', () => ({ useAssistantState: () => ({}) }))
vi.mock('../src/api', () => ({
  ApiError: class extends Error {},
  api: {
    visitCourse: vi.fn().mockResolvedValue({ last_opened_at: '2026-10-14' }),
    listCourses: vi.fn().mockResolvedValue([{ id: 'c', name: 'Course' }]),
    listMaterials: vi.fn().mockResolvedValue([{ id: 'm1' }, { id: 'm2' }]),
    listNotes: vi.fn().mockResolvedValue([]), getKnowledgeGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    listPages: vi.fn((id: string) => Promise.resolve([{ material_id: id, page_number: 1 }, { material_id: id, page_number: 5 }])),
    getLatestMaterialJob: vi.fn().mockResolvedValue(undefined),
    uploadMaterial: vi.fn().mockResolvedValue({ job: { id: 'job', status: 'failed' }, material: { id: 'm2' } }),
  },
}))
afterEach(cleanup)

test('jumping from a source in another lecture retains its requested page', async () => {
  const { result } = renderHook(() => useWorkspaceState(), {
    wrapper: ({ children }) => <MemoryRouter initialEntries={['/courses/c/materials']}>{children}</MemoryRouter>,
  })
  await waitFor(() => expect(result.current.selectedPageNumber).toBe(1))
  act(() => result.current.openMaterialSource('m2', 5))
  await waitFor(() => expect(result.current.pages[0]?.material_id).toBe('m2'))
  expect(result.current.selectedPageNumber).toBe(5)
})
test('target book is carried through workspace upload to the multipart API boundary', async () => {
  const { result } = renderHook(() => useWorkspaceState(), { wrapper: ({ children }) => <MemoryRouter initialEntries={['/courses/c/materials?notebook=b2']}>{children}</MemoryRouter> })
  await waitFor(() => expect(result.current.course?.id).toBe('c'))
  await act(() => result.current.uploadMaterial(new File(['source'], 'source.docx'), '第二讲', '', false, 'b2'))
  expect(vi.mocked(api.uploadMaterial).mock.calls.at(-1)?.[6]).toBe('b2')
  expect(result.current.selectedMaterialId).toBe('m2')
})
test('forest display and directory browsing do not visit a course; entering its book does', async () => {
  vi.mocked(api.visitCourse).mockClear()
  let navigate!: ReturnType<typeof useNavigate>
  function Controls() { navigate = useNavigate(); return null }
  renderHook(() => useWorkspaceState(), { wrapper: ({ children }) => <MemoryRouter initialEntries={['/forest']}><Controls />{children}</MemoryRouter> })
  await waitFor(() => expect(api.listCourses).toHaveBeenCalled())
  expect(api.visitCourse).not.toHaveBeenCalled()
  act(() => navigate('/courses/c/notebooks/b2'))
  await waitFor(() => expect(api.visitCourse).toHaveBeenCalledWith('c'))
})
