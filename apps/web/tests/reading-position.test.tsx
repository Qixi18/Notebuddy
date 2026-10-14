import { cleanup, fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { positionWriter } from '../src/features/notebook/readingPosition'
vi.mock('../src/api', () => ({ ApiError: class extends Error { constructor(message: string, readonly status: number) { super(message) } }, api: { getNotebook: vi.fn(), getNotebookById: vi.fn(), getReadingPosition: vi.fn(), saveReadingPosition: vi.fn(), getNotebookChapter: vi.fn(), getChapter: vi.fn() } }))
vi.mock('../src/pages/NotesPage', () => ({ NoteSectionReader: ({ noteId }: { noteId: string }) => <p>正文 {noteId}</p> }))
const s1 = { id: 'n1', notebook_id: 'book', material_id: 'm1', tree_slot: 0, title: '第一节' }
const s2 = { ...s1, id: 'n2', material_id: 'm2', title: '第二节' }
const outline = { id: 'book', course_id: 'c', title: '本', chapters: [{ id: 'm1', title: '讲1', sections: [s1] }, { id: 'm2', title: '讲2', sections: [s2] }], historical_sections: [], removed_chapters: [] }
const position = { notebook_id: 'book', chapter_id: 'm2', note_id: 'n2', mode: 'chapter', section_offset: .5, revision: 3, updated_at: 'now' }
function mount(query = '') {
  const workspace = { notes: [s1, s2], materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn() } as unknown as WorkspaceContextValue
  return render(<MemoryRouter initialEntries={[`/courses/c/notebooks/book${query}`]}><WorkspaceProvider value={workspace}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></WorkspaceProvider></MemoryRouter>)
}
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); HTMLElement.prototype.scrollIntoView = vi.fn(); vi.mocked(api.getChapter).mockResolvedValue({ material_id: 'm1', sections: [] }); vi.mocked(api.getNotebook).mockResolvedValue(outline as never); vi.mocked(api.getNotebookById).mockResolvedValue(outline as never); vi.mocked(api.getReadingPosition).mockResolvedValue(position as never); vi.mocked(api.getNotebookChapter).mockResolvedValue({ material_id: 'm1', sections: [] }); vi.mocked(api.saveReadingPosition).mockImplementation(async (_c, _b, p) => ({ ...p, notebook_id: 'book', revision: p.expected_revision + 1, updated_at: 'now' })) })
afterEach(cleanup)
test('branch resumes the saved section while an explicit leaf wins the bookmark', async () => {
  const result = mount()
  expect(await screen.findByText('正文 n2')).toBeTruthy()
  result.unmount()
  mount('?chapter=m1&section=n1')
  expect(await screen.findByText('正文 n1')).toBeTruthy()
  expect(screen.queryByText('正文 n2')).toBeNull()
})
test('removed bookmark stays in its own directory and explains the missing target', async () => {
  vi.mocked(api.getReadingPosition).mockResolvedValue({ ...position, note_id: 'deleted' } as never)
  mount()
  expect(await screen.findByText(/上次阅读位置已失效/)).toBeTruthy()
  expect(screen.queryByText('正文 n1')).toBeNull()
})
test('scroll in the actual reading container saves a relative section offset with server revision', async () => {
  mount('?chapter=m1&section=n1')
  await screen.findByText('正文 n1')
  const container = screen.getByRole('main', { name: '笔记本正文' })
  const article = document.getElementById('section-n1')!
  vi.spyOn(container, 'getBoundingClientRect').mockReturnValue({ top: 100 } as DOMRect)
  vi.spyOn(article, 'getBoundingClientRect').mockReturnValue({ top: -100, height: 400 } as DOMRect)
  fireEvent.scroll(container)
  await waitFor(() => expect(api.saveReadingPosition).toHaveBeenCalled(), { timeout: 2000 })
  expect(vi.mocked(api.saveReadingPosition).mock.calls.at(-1)?.[2]).toMatchObject({ note_id: 'n1', section_offset: .5, expected_revision: 3 })
})
test('a 409 stops bookmark writes and surfaces an explicit retry instead of silently overwriting', async () => {
  vi.mocked(api.saveReadingPosition).mockRejectedValue(new ApiError('冲突', 409))
  mount('?chapter=m1&section=n1')
  await screen.findByText('正文 n1')
  fireEvent.scroll(screen.getByRole('main', { name: '笔记本正文' }))
  expect(await screen.findByText(/阅读位置已在其他窗口更新/)).toBeTruthy()
  const count = vi.mocked(api.saveReadingPosition).mock.calls.length
  fireEvent.scroll(screen.getByRole('main', { name: '笔记本正文' }))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 750)) })
  expect(vi.mocked(api.saveReadingPosition).mock.calls.length).toBe(count)
  expect(screen.getByRole('button', { name: '重试保存当前位置' })).toBeTruthy()
})
test('failed cached progress requires an explicit retry even after a fresh writer is created', async () => {
  sessionStorage.setItem('notebuddy.reading.pending.cached.book', JSON.stringify({ chapter_id: 'm1', note_id: 'n1', mode: 'chapter', section_offset: .7 }))
  const writer = positionWriter('cached', 'book', position as never)
  await expect(writer.save({ chapter_id: 'm1', note_id: 'n1', mode: 'chapter', section_offset: .2 })).rejects.toThrow(/重试/)
  expect(api.saveReadingPosition).not.toHaveBeenCalled()
})
test('two saves for one book serialize CAS revisions and clear only the latest pending position', async () => {
  let finishFirst!: (value: unknown) => void
  vi.mocked(api.saveReadingPosition).mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve as never }))
    .mockImplementationOnce(async (_c, _b, p) => ({ ...p, notebook_id: 'serial', revision: p.expected_revision + 1, updated_at: 'now' }))
  const writer = positionWriter('serial-course', 'serial', position as never)
  const one = writer.save({ chapter_id: 'm1', note_id: 'n1', mode: 'chapter', section_offset: .2 })
  const two = writer.save({ chapter_id: 'm2', note_id: 'n2', mode: 'book', section_offset: .7 })
  await waitFor(() => expect(vi.mocked(api.saveReadingPosition).mock.calls.length).toBe(1))
  expect(JSON.parse(sessionStorage.getItem('notebuddy.reading.pending.serial-course.serial')!).note_id).toBe('n2')
  finishFirst({ revision: 4 })
  await Promise.all([one, two])
  expect(vi.mocked(api.saveReadingPosition).mock.calls.map(call => call[2].expected_revision)).toEqual([3, 4])
  expect(sessionStorage.getItem('notebuddy.reading.pending.serial-course.serial')).toBeNull()
})
test('first entry without a bookmark selects the first genuine section', async () => {
  vi.mocked(api.getReadingPosition).mockResolvedValue(null)
  mount()
  expect(await screen.findByText('正文 n1')).toBeTruthy()
})
test('switching books never queues an old section into the new book during loading', async () => {
  const newSection = { ...s1, id: 'n3', notebook_id: 'second', material_id: 'm3' }
  vi.mocked(api.getNotebookById).mockImplementation(async (_c, id) => id === 'second' ? { ...outline, id: 'second', title: '另一本', chapters: [{ id: 'm3', title: '讲3', sections: [newSection] }] } as never : outline as never)
  vi.mocked(api.getReadingPosition).mockResolvedValue(null)
  function Switch() { const navigate = useNavigate(); return <><NotebookPage /><button onClick={() => navigate('/courses/switch-course/notebooks/second')}>切换本</button></> }
  render(<MemoryRouter initialEntries={['/courses/switch-course/notebooks/book']}><WorkspaceProvider value={{ notes: [s1, newSection], materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn() } as unknown as WorkspaceContextValue}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<Switch />} /></Routes></WorkspaceProvider></MemoryRouter>)
  await screen.findByText('正文 n1')
  fireEvent.click(screen.getByRole('button', { name: '切换本' }))
  await screen.findByText('正文 n3')
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) })
  expect(vi.mocked(api.saveReadingPosition).mock.calls.filter(call => call[1] === 'second' && call[2].note_id === 'n1')).toHaveLength(0)
})
