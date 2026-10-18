import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { HomePage } from '../src/pages/HomePage'

vi.mock('../src/api', () => ({ api: {
  getNotebook: vi.fn(), getNotebookById: vi.fn(), getReadingPosition: vi.fn(), saveReadingPosition: vi.fn(),
  getChapter: vi.fn(), getNotebookChapter: vi.fn(), getNote: vi.fn(), getForest: vi.fn(), getCourseTree: vi.fn(),
  listMaterials: vi.fn().mockResolvedValue([]), listNotes: vi.fn().mockResolvedValue([]), listNotebooks: vi.fn(), createNotebook: vi.fn(),
} }))
vi.mock('../src/features/notes/NoteSectionReader', () => ({ NoteSectionReader: ({ noteId }: { noteId: string }) => <p>正文 {noteId}</p> }))
const section = { id: 'n2', notebook_id: 'b2', material_id: 'm2', tree_slot: 0, title: '第二本知识点' }
const second = { id: 'b2', course_id: 'c', title: '第二本', tree_slot: 1, order_revision: 0, chapters: [{ id: 'm2', title: '第二讲', sections: [section] }], historical_sections: [], removed_chapters: [] }
const first = { ...second, id: 'b1', title: '默认本', chapters: [] }
const course = { id: 'c', name: '课程', created_at: '2026-10-01', last_opened_at: null }
const forestCourse = { course_id: 'c', name: '课程', semester: 1, level: 'foundation', learning_state: 'planned', position: 0, revision: 0, note_count: 1, material_count: 1, prerequisites: [] }
function Location() { const location = useLocation(); return <output aria-label="位置">{location.pathname}{location.search}</output> }
function mount(path: string, page: React.ReactNode) {
  const workspace = { courses: [course], notes: [{ ...section, course_id: 'c', content_markdown: '用户正文' }], materials: [], upsertNotes: vi.fn(), setSelectedNoteId: vi.fn(), createCourse: vi.fn(), noteDirty: false } as unknown as WorkspaceContextValue
  return render(<MemoryRouter initialEntries={[path]}><WorkspaceProvider value={workspace}><Routes><Route path="/" element={page} /><Route path="/courses/:courseId/notebooks/:notebookId" element={page} /><Route path="/courses/:courseId/materials" element={<p>上传资料</p>} /></Routes><Location /></WorkspaceProvider></MemoryRouter>)
}
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear()
  vi.mocked(api.getNotebook).mockResolvedValue(first as never)
  vi.mocked(api.getNotebookById).mockResolvedValue(second as never)
  vi.mocked(api.getReadingPosition).mockResolvedValue(null)
  vi.mocked(api.getNotebookChapter).mockResolvedValue({ material_id: 'm2', sections: [] })
  vi.mocked(api.getForest).mockResolvedValue({ courses: [forestCourse] } as never)
  vi.mocked(api.getCourseTree).mockResolvedValue({ course_id: 'c', notebooks: [second] } as never)
  vi.mocked(api.listNotebooks).mockResolvedValue([first, second] as never)
  vi.mocked(api.createNotebook).mockResolvedValue({ ...second, id: 'new-book', title: '新本' } as never)
})
afterEach(cleanup)
test('explicit book opens its own content and upload keeps the exact target book', async () => {
  mount('/courses/c/notebooks/b2?chapter=m2&section=n2', <NotebookPage />)
  await screen.findByRole('heading', { name: '第二本', level: 1 })
  expect(await screen.findByText('正文 n2')).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '上传下一讲' }))
  expect(screen.getByLabelText('位置').textContent).toBe('/courses/c/materials?notebook=b2')
})
test('home root creates a named book then navigates to upload that book', async () => {
  mount('/', <HomePage />)
  fireEvent.click(await screen.findByRole('button', { name: '课程菜单：课程' }))
  fireEvent.click(screen.getByRole('button', { name: '新建笔记本' }))
  fireEvent.change(screen.getByLabelText('笔记本名称'), { target: { value: '新本' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并上传' }))
  await waitFor(() => expect(screen.getByLabelText('位置').textContent).toBe('/courses/c/materials?notebook=new-book'))
})
test('home root expands the chosen book rather than the default book', async () => {
  mount('/', <HomePage />)
  fireEvent.click(await screen.findByRole('button', { name: '课程菜单：课程' }))
  fireEvent.click(screen.getByRole('button', { name: '扩充现有笔记本' }))
  fireEvent.change(await screen.findByLabelText('选择笔记本'), { target: { value: 'b2' } })
  fireEvent.click(screen.getByRole('button', { name: '上传到此本' }))
  expect(screen.getByLabelText('位置').textContent).toBe('/courses/c/materials?notebook=b2')
})
