import { cleanup, fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { useCallback, useState } from 'react'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { positionWriter } from '../src/features/notebook/readingPosition'
vi.mock('../src/api', () => ({ ApiError: class extends Error { constructor(message: string, readonly status: number) { super(message) } }, api: { getNotebook: vi.fn(), getNotebookById: vi.fn(), getReadingPosition: vi.fn(), saveReadingPosition: vi.fn(), getNotebookChapter: vi.fn(), getChapter: vi.fn(), getNote: vi.fn() } }))
vi.mock('../src/pages/NotesPage', () => ({ NoteSectionReader: ({ noteId }: { noteId: string }) => <p>正文 {noteId}</p> }))
const s1 = { id: 'n1', notebook_id: 'book', material_id: 'm1', tree_slot: 0, title: '第一节' }
const s2 = { ...s1, id: 'n2', material_id: 'm2', title: '第二节' }
const outline = { id: 'book', course_id: 'c', title: '本', chapters: [{ id: 'm1', title: '讲1', sections: [s1] }, { id: 'm2', title: '讲2', sections: [s2] }], historical_sections: [], removed_chapters: [] }
const position = { notebook_id: 'book', chapter_id: 'm2', note_id: 'n2', mode: 'chapter', section_offset: .5, revision: 3, updated_at: 'now' }
function mount(query = '', courseId = 'c') {
  const workspace = { notes: [s1, s2], materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn() } as unknown as WorkspaceContextValue
  const page = (value: WorkspaceContextValue) => <MemoryRouter initialEntries={[`/courses/${courseId}/notebooks/book${query}`]}><WorkspaceProvider value={value}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></WorkspaceProvider></MemoryRouter>
  const result = render(page(workspace))
  return { ...result, updateNotes: () => result.rerender(page({ ...workspace, notes: workspace.notes.map(note => ({ ...note, revision_number: 2 })) })) }
}
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); HTMLElement.prototype.scrollIntoView = vi.fn(); vi.mocked(api.getChapter).mockResolvedValue({ material_id: 'm1', sections: [] }); vi.mocked(api.getNotebook).mockResolvedValue(outline as never); vi.mocked(api.getNotebookById).mockResolvedValue(outline as never); vi.mocked(api.getReadingPosition).mockResolvedValue(position as never); vi.mocked(api.getNotebookChapter).mockResolvedValue({ material_id: 'm1', sections: [] }); vi.mocked(api.saveReadingPosition).mockImplementation(async (_c, _b, p) => ({ ...p, notebook_id: 'book', revision: p.expected_revision + 1, updated_at: 'now' })) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })
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
test.each(['chapter', 'book'])('automatic %s resume rejects a removed chapter even when its original note remains', async mode => {
  vi.mocked(api.getNotebookById).mockResolvedValue({ ...outline, chapters: [outline.chapters[0]], removed_chapters: [{ ...outline.chapters[1], deleted_at: '2026-10-15T00:00:00Z' }] } as never)
  vi.mocked(api.getReadingPosition).mockResolvedValue({ ...position, mode } as never)
  vi.mocked(api.getNote).mockResolvedValue({ ...s2, course_id: 'c' } as never)
  const page = mount()
  expect(await screen.findByText(/上次阅读位置已失效/)).toBeTruthy()
  expect(screen.getByRole('navigation', { name: '笔记本目录' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '1. 讲1' })).toBeTruthy()
  expect(screen.queryByText('正文 n2')).toBeNull()
  expect(screen.queryByText('正文 n1')).toBeNull()
  expect(api.getNote).not.toHaveBeenCalled()
  fireEvent.scroll(screen.getByRole('main', { name: '笔记本正文' }))
  fireEvent(window, new Event('pagehide'))
  page.unmount()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 650)) })
  expect(api.saveReadingPosition).not.toHaveBeenCalled()
})

test('an explicit old section link still opens the retained note from a removed chapter', async () => {
  vi.mocked(api.getNotebookById).mockResolvedValue({ ...outline, chapters: [outline.chapters[0]], removed_chapters: [{ ...outline.chapters[1], deleted_at: '2026-10-15T00:00:00Z' }] } as never)
  vi.mocked(api.getNote).mockResolvedValue({ ...s2, course_id: 'c' } as never)
  mount('?chapter=m2&section=n2')
  expect(await screen.findByText('正文 n2')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '讲2 · 资料已移除' })).toBeTruthy()
  expect(screen.queryByText(/上次阅读位置已失效/)).toBeNull()
  await waitFor(() => expect(api.getNote).toHaveBeenCalledWith('n2'))
})

test('a historical section bookmark with no material still resumes its retained note', async () => {
  const historical = { ...s2, material_id: null }
  vi.mocked(api.getNotebookById).mockResolvedValue({ ...outline, chapters: [outline.chapters[0]], historical_sections: [historical] } as never)
  vi.mocked(api.getReadingPosition).mockResolvedValue({ ...position, chapter_id: null } as never)
  vi.mocked(api.getNote).mockResolvedValue({ ...historical, course_id: 'c' } as never)
  mount()
  expect(await screen.findByText('正文 n2')).toBeTruthy()
  expect(screen.queryByText(/上次阅读位置已失效/)).toBeNull()
})

test('scroll in the actual reading container saves a relative section offset with server revision', async () => {
  mount('?chapter=m1&section=n1')
  await screen.findByText('正文 n1')
  await waitFor(() => expect(screen.queryByText('正在按章节读取正文…')).toBeNull())
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
test('switching books loads the uncached book bookmark and body, restores and saves its own position', async () => {
  const newSection = { ...s1, id: 'n3', notebook_id: 'second', material_id: 'm3', content_markdown: '第二本新正文' }
  vi.mocked(api.getNotebookById).mockImplementation(async (_c, id) => id === 'second' ? { ...outline, id: 'second', title: '另一本', chapters: [{ id: 'm3', title: '讲3', sections: [newSection] }] } as never : outline as never)
  vi.mocked(api.getReadingPosition).mockImplementation(async (_c, id) => id === 'second' ? { ...position, notebook_id: 'second', chapter_id: 'm3', note_id: 'n3', section_offset: .65, revision: 7 } as never : null)
  vi.mocked(api.getNotebookChapter).mockImplementation(async (_c, _b, id) => ({ material_id: id, sections: id === 'm3' ? [newSection] : [] }) as never)
  let sectionTop = 100
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function () {
    return { top: this.id === 'section-n3' ? sectionTop : 100, height: 400 } as DOMRect
  })
  function Switch() {
    const navigate = useNavigate()
    const [notes, setNotes] = useState([s1])
    const upsertNotes = useCallback((incoming: typeof s1[]) => setNotes(current => [...current.filter(note => !incoming.some(next => next.id === note.id)), ...incoming]), [])
    return <WorkspaceProvider value={{ notes, materials: [], upsertNotes, setSelectedNoteId: vi.fn() } as unknown as WorkspaceContextValue}><NotebookPage /><button onClick={() => navigate('/courses/switch-course/notebooks/second')}>切换本</button></WorkspaceProvider>
  }
  render(<MemoryRouter initialEntries={['/courses/switch-course/notebooks/book']}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<Switch />} /></Routes></MemoryRouter>)
  await screen.findByText('正文 n1')
  fireEvent.click(screen.getByRole('button', { name: '切换本' }))
  await waitFor(() => expect(api.getReadingPosition).toHaveBeenCalledWith('switch-course', 'second'))
  await screen.findByText('正文 n3')
  expect(api.getNotebookChapter).toHaveBeenCalledWith('switch-course', 'second', 'm3')
  const container = screen.getByRole('main', { name: '笔记本正文' })
  await waitFor(() => expect(container.scrollTop).toBe(260))
  sectionTop = -100
  fireEvent.scroll(container)
  await waitFor(() => expect(vi.mocked(api.saveReadingPosition).mock.calls.some(call => call[1] === 'second' && call[2].note_id === 'n3' && call[2].section_offset === .5 && call[2].expected_revision === 7)).toBe(true))
  expect(vi.mocked(api.saveReadingPosition).mock.calls.filter(call => call[1] === 'second' && call[2].note_id === 'n1')).toHaveLength(0)
})
test('cached text does not restore early; the completed chapter restores once and later note updates keep the reader scroll', async () => {
  let finishChapter!: (value: unknown) => void
  let bodyReady = false
  vi.mocked(api.getNotebookChapter).mockImplementationOnce(() => new Promise(resolve => { finishChapter = resolve as never }))
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function () {
    if (this.classList.contains('notebook-content')) return { top: 100 } as DOMRect
    if (this.id === 'section-n2') return { top: 100, height: bodyReady ? 800 : 200 } as DOMRect
    return { top: 100, height: 200 } as DOMRect
  })
  const page = mount('', 'stable')
  await screen.findByText('正在按章节读取正文…')
  const container = screen.getByRole('main', { name: '笔记本正文' })
  expect(container.scrollTop).toBe(0)
  await act(async () => { bodyReady = true; finishChapter({ material_id: 'm2', sections: [] }) })
  await waitFor(() => expect(screen.queryByText('正在按章节读取正文…')).toBeNull())
  expect(container.scrollTop).toBe(400)
  container.scrollTop = 520
  fireEvent.scroll(container)
  page.updateNotes()
  // A same-section rerender must not reset scroll to the original bookmark.
  expect(container.scrollTop).toBe(520)
  page.unmount()
  vi.restoreAllMocks()
})
test('leaving before the debounce samples the latest container offset even if its final scroll event is pending', async () => {
  let articleTop = 20
  const page = mount('?chapter=m1&section=n1', 'leave-latest')
  await screen.findByText('正文 n1')
  await waitFor(() => expect(screen.queryByText('正在按章节读取正文…')).toBeNull())
  const container = screen.getByRole('main', { name: '笔记本正文' })
  const article = document.getElementById('section-n1')!
  vi.spyOn(container, 'getBoundingClientRect').mockReturnValue({ top: 100 } as DOMRect)
  vi.spyOn(article, 'getBoundingClientRect').mockImplementation(() => ({ top: articleTop, height: 400 } as DOMRect))
  fireEvent.scroll(container) // 20% was observed by the scroll listener.
  articleTop = -220 // 80% is now visible; the next native scroll event has not arrived.
  page.unmount()
  await waitFor(() => expect(api.saveReadingPosition).toHaveBeenCalled())
  expect(vi.mocked(api.saveReadingPosition).mock.calls.at(-1)?.[2]).toMatchObject({ note_id: 'n1', section_offset: .8 })
  vi.restoreAllMocks()
})
