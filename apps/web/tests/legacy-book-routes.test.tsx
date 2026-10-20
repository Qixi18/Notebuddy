import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotesPage } from '../src/pages/NotesPage'
vi.mock('../src/api', () => ({ api: { getNotebook: vi.fn(), getNote: vi.fn(), getCourseTree: vi.fn() } }))
function Result() { const location = useLocation(); return <p>{location.pathname}{location.search}</p> }
function mount(path: string) { render(<MemoryRouter initialEntries={[path]}><WorkspaceProvider value={{ notes: [], materials: [] } as unknown as WorkspaceContextValue}><Routes><Route path="/courses/:courseId/notes/:noteId" element={<NotesPage />} /><Route path="/courses/:courseId/notebooks/:notebookId" element={<Result />} /></Routes></WorkspaceProvider></MemoryRouter>) }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebook).mockResolvedValue({ id: 'default', course_id: 'c', title: '默认本', chapters: [], historical_sections: [], removed_chapters: [] } as never)
  vi.mocked(api.getNote).mockResolvedValue({ id: 'n', course_id: 'c', notebook_id: 'second', material_id: 'lecture' } as never)
  vi.mocked(api.getCourseTree).mockResolvedValue({ course_id: 'c', notebooks: [{ id: 'second', chapters: [{ id: 'lecture' }], removed_chapters: [] }] } as never)
})
afterEach(cleanup)
test('old note links preserve the real book and reject another course', async () => {
  mount('/courses/c/notes/n'); await screen.findByText('/courses/c/notebooks/second?chapter=lecture&section=n')
  cleanup(); vi.mocked(api.getNote).mockResolvedValue({ id: 'n', course_id: 'other', notebook_id: 'second', material_id: 'lecture' } as never)
  mount('/courses/c/notes/n'); await screen.findByText('这条笔记属于其他课程。')
})
