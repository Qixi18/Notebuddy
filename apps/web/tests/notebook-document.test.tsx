import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status: number) { super(message) } },
  api: {
    getNotebookById: vi.fn(), getNotebookDocument: vi.fn(), saveNotebookDocument: vi.fn(),
    renameNotebook: vi.fn(), getNotebookChapter: vi.fn(), getNote: vi.fn(),
  },
}))

const outline = { id: 'book', course_id: 'course', title: '一元微积分', tree_slot: 0, order_revision: 0, chapters: [], historical_sections: [], removed_chapters: [] }
const blocks = [{ id: 'heading', type: 'h1', text: '极限与连续' }, { id: 'body', type: 'p', text: '原来的正文' }]
const setDocumentDirty = vi.fn()

function mount() {
  const uploadMaterial = vi.fn().mockResolvedValue(undefined)
  const refreshCurrentMaterials = vi.fn().mockResolvedValue(undefined)
  const workspace = {
    course: { id: 'course', name: '数学分析（上）' }, materials: [], busy: false,
    uploadMaterial, refreshCurrentMaterials, setDocumentDirty,
  } as unknown as WorkspaceContextValue
  return { ...render(<MemoryRouter initialEntries={['/courses/course/notebooks/book']}><WorkspaceProvider value={workspace}><Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes></WorkspaceProvider></MemoryRouter>), uploadMaterial, refreshCurrentMaterials }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebookById).mockResolvedValue(outline as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue({ blocks, revision: 2, updated_at: '2026-10-20' } as never)
  vi.mocked(api.saveNotebookDocument).mockImplementation(async (_course, _book, next, revision) => ({ blocks: next, revision: revision + 1, updated_at: '2026-10-20' }))
})
afterEach(cleanup)

test('shows course ownership, document headings and editable body', async () => {
  mount()
  expect(await screen.findByRole('textbox', { name: '笔记名称' })).toHaveProperty('value', '一元微积分')
  expect(screen.getAllByText('数学分析（上）').length).toBeGreaterThan(0)
  expect(screen.getByRole('navigation', { name: '笔记目录' }).textContent).toContain('极限与连续')
  expect(screen.getByRole('textbox', { name: '笔记正文' })).toHaveProperty('value', '原来的正文')
  expect(screen.getByRole('button', { name: /课程资料/ }).getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByRole('button', { name: /笔记目录/ }).getAttribute('aria-expanded')).toBe('true')
})

test('editing a heading updates the outline and saves with its revision', async () => {
  mount()
  const heading = await screen.findByRole('textbox', { name: '章节标题' })
  fireEvent.change(heading, { target: { value: '新的极限章节' } })
  expect(screen.getByRole('navigation', { name: '笔记目录' }).textContent).toContain('新的极限章节')
  await waitFor(() => expect(api.saveNotebookDocument).toHaveBeenCalledWith('course', 'book', expect.arrayContaining([expect.objectContaining({ text: '新的极限章节' })]), 2), { timeout: 3000 })
  await waitFor(() => expect(setDocumentDirty).toHaveBeenLastCalledWith(false))
})

test('resource and outline groups collapse; upload targets the current notebook', async () => {
  const { uploadMaterial, refreshCurrentMaterials } = mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.click(screen.getByRole('button', { name: /笔记目录/ }))
  expect(screen.queryByRole('navigation', { name: '笔记目录' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /笔记目录/ }))
  expect(screen.getByRole('navigation', { name: '笔记目录' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('选择课程资料'), { target: { files: [new File(['sample'], '第一讲.pdf', { type: 'application/pdf' })] } })
  await waitFor(() => expect(uploadMaterial).toHaveBeenCalledWith(expect.any(File), '第一讲', '', false, 'book'))
  await waitFor(() => expect(refreshCurrentMaterials).toHaveBeenCalled())
})
