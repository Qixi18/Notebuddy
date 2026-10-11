import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { useWorkspaceState } from '../src/features/workspace/useWorkspaceState'

vi.mock('../src/features/assistant/useAssistantState', () => ({ useAssistantState: () => ({}) }))
vi.mock('../src/api', () => ({
  ApiError: class extends Error {},
  api: {
    listCourses: vi.fn().mockResolvedValue([{ id: 'c', name: 'Course' }]),
    listMaterials: vi.fn().mockResolvedValue([{ id: 'm1' }, { id: 'm2' }]),
    listNotes: vi.fn().mockResolvedValue([]), getKnowledgeGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    listPages: vi.fn((id: string) => Promise.resolve([{ material_id: id, page_number: 1 }, { material_id: id, page_number: 5 }])),
    getLatestMaterialJob: vi.fn().mockResolvedValue(undefined),
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
