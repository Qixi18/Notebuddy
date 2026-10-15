import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { NotesPage } from '../src/pages/NotesPage'
vi.mock('../src/api', () => ({ api: { getNotebook: vi.fn(), getNote: vi.fn(), getCourseTree: vi.fn() } }))
function Result() { const location = useLocation(); return <p>{location.pathname}{location.search}</p> }
function mount(path: string) { render(<MemoryRouter initialEntries={[path]}><WorkspaceProvider value={{ notes: [], materials: [] } as unknown as WorkspaceContextValue}><Routes><Route path="/courses/:courseId/notebook" element={<NotebookPage />} /><Route path="/courses/:courseId/notes/:noteId" element={<NotesPage />} /><Route path="/courses/:courseId/notebooks/:notebookId" element={<Result />} /></Routes></WorkspaceProvider></MemoryRouter>) }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebook).mockResolvedValue({ id: 'default', course_id: 'c', title: '默认本', chapters: [], historical_sections: [], removed_chapters: [] } as never)
  vi.mocked(api.getNote).mockResolvedValue({ id: 'n', course_id: 'c', notebook_id: 'second', material_id: 'lecture' } as never)
  vi.mocked(api.getCourseTree).mockResolvedValue({ course_id: 'c', notebooks: [{ id: 'second', chapters: [{ id: 'lecture' }], removed_chapters: [] }] } as never)
})
afterEach(cleanup)
test('old singular section links resolve the real second book', async () => { mount('/courses/c/notebook?section=n'); await screen.findByText('/courses/c/notebooks/second?chapter=lecture&section=n') })
test('old chapter-only links resolve ownership across all books', async () => { mount('/courses/c/notebook?chapter=lecture'); await screen.findByText('/courses/c/notebooks/second?chapter=lecture') })
test('old note links preserve the real book and reject another course', async () => {
  mount('/courses/c/notes/n'); await screen.findByText('/courses/c/notebooks/second?chapter=lecture&section=n')
  cleanup(); vi.mocked(api.getNote).mockResolvedValue({ id: 'n', course_id: 'other', notebook_id: 'second', material_id: 'lecture' } as never)
  mount('/courses/c/notes/n'); await screen.findByText('这条笔记属于其他课程。')
})
test('an empty legacy course shows the create entry rather than an invented notebook', async () => {
  vi.mocked(api.getNotebook).mockRejectedValue(new Error('此课程尚无笔记本，请先新建笔记本'))
  mount('/courses/c/notebook')
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('此课程尚无笔记本'))
  expect(screen.getByRole('button', { name: '新建笔记本' })).toBeTruthy()
})
