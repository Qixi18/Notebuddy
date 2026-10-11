import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { NoteSectionReader } from '../src/pages/NotesPage'

const state = vi.hoisted(() => ({ workspace: {} as Record<string, unknown> }))
vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => state.workspace, featurePath: () => '/materials' }))
vi.mock('../src/api', () => ({ api: {
  getNoteSources: vi.fn().mockResolvedValue([]), getNoteRevisions: vi.fn().mockResolvedValue([]),
  getNoteWebSources: vi.fn().mockResolvedValue([]), listSuggestions: vi.fn().mockResolvedValue([{ id: 's', proposed_markdown: 'suggestion', status: 'pending' }]),
  reviewSuggestion: vi.fn(),
} }))
afterEach(cleanup)

test('accepting an earlier suggestion cannot reselect a note after navigation', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.reviewSuggestion).mockReturnValue(new Promise((done) => { resolve = done }) as never)
  const first = { id: 'n1', course_id: 'c', title: 'First', content_markdown: 'First saved', revision_number: 1 }
  const second = { id: 'n2', course_id: 'c', title: 'Second', content_markdown: 'Second saved', revision_number: 1 }
  const select = vi.fn(), reload = vi.fn(), upsert = vi.fn()
  state.workspace = { courseId: 'c', notes: [first, second], selectedNote: first, setSelectedNoteId: select, reloadNote: reload, upsertNotes: upsert, materials: [], setError: vi.fn(), noteDirty: false, noteSaving: false }
  const page = (id: string) => <MemoryRouter initialEntries={['/courses/c/notebook']}><Routes><Route path="/courses/:courseId/notebook" element={<NoteSectionReader noteId={id} />} /></Routes></MemoryRouter>
  const { rerender } = render(page('n1'))
  fireEvent.click(await screen.findByRole('button', { name: '接受并生成版本' }))
  state.workspace = { ...state.workspace, selectedNote: second, noteDirty: true }
  rerender(page('n2'))
  await act(async () => { resolve({ ...first, content_markdown: 'suggestion', revision_number: 2 }) })
  expect(select).not.toHaveBeenCalledWith('n1')
  expect(reload).not.toHaveBeenCalled()
})
