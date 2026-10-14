import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { NotebookPage } from '../src/pages/NotebookPage'

const state = vi.hoisted(() => ({ workspace: {} as Record<string, unknown> }))
vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => state.workspace }))
vi.mock('../src/pages/NotesPage', () => ({ NoteSectionReader: ({ noteId }: { noteId: string }) => <div>{noteId}</div> }))
vi.mock('../src/api', () => ({ api: { getNotebookById: vi.fn(), getNotebookChapter: vi.fn(), getNote: vi.fn(), getReadingPosition: vi.fn().mockResolvedValue(null), saveReadingPosition: vi.fn().mockResolvedValue({revision: 1}) } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const chapter = { id: 'm', title: 'Lecture', sections: [], status: 'pending' }
const book = { id: 'b', tree_slot: 0, course_id: 'c', title: 'Course', chapters: [chapter], historical_sections: [], removed_chapters: [], order_revision: 0 }
const renderPage = () => <MemoryRouter initialEntries={['/courses/c/notebooks/b?chapter=m']}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></MemoryRouter>

test('a processing chapter receives its generated sections when the job finishes', async () => {
  const material = { id: 'm', status: 'pending' }
  state.workspace = { notes: [], materials: [material], job: { id: 'j', status: 'pending' }, upsertNotes: vi.fn(), setSelectedNoteId: vi.fn(), courseContentLoading: false, noteDirty: false }
  vi.mocked(api.getNotebookById).mockResolvedValue(book as never)
  vi.mocked(api.getNotebookChapter).mockResolvedValue({ ...chapter, sections: [] } as never)
  const { rerender } = render(renderPage())
  await screen.findByText('资料处理中')
  const section = { id: 'n', material_id: 'm', title: 'Matrix', revision_number: 1 }
  vi.mocked(api.getNotebookById).mockResolvedValue({ ...book, chapters: [{ ...chapter, status: 'completed', sections: [section] }] } as never)
  vi.mocked(api.getNotebookChapter).mockResolvedValue({ ...chapter, sections: [{ ...section, content_markdown: 'generated body' }] } as never)
  state.workspace = { ...state.workspace, materials: [{ ...material, status: 'completed' }], job: { id: 'j', status: 'completed' } }
  rerender(renderPage())
  await waitFor(() => expect(screen.getByRole('button', { name: 'Matrix' })).toBeTruthy())
})

test('whole book includes every historical section in order', async () => {
  const history = [
    { id: 'h1', course_id: 'c', material_id: null, notebook_id: 'b', title: 'Old one', content_markdown: 'First historical body', revision_number: 1 },
    { id: 'h2', course_id: 'c', material_id: null, notebook_id: 'b', title: 'Old two', content_markdown: 'Second historical body', revision_number: 1 },
  ]
  state.workspace = { notes: history, materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn(), courseContentLoading: false, noteDirty: false }
  vi.mocked(api.getNotebookById).mockResolvedValue({ ...book, chapters: [], historical_sections: history } as never)
  vi.mocked(api.getNote).mockImplementation(async (id) => history.find((n) => n.id === id) as never)
  render(<MemoryRouter initialEntries={['/courses/c/notebooks/b?mode=book']}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></MemoryRouter>)
  // The selected section uses the real reader in the app; the other section must still render its body.
  await screen.findByRole('button', { name: 'Old two' })
  expect(screen.getByText('Second historical body')).toBeTruthy()
  await waitFor(() => expect(api.getNote).toHaveBeenCalledWith('h2'))
})
