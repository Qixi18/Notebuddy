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
    uploadNotebookAttachment: vi.fn(), listNotebookRevisions: vi.fn(), getNotebookRevision: vi.fn(),
    restoreNotebookRevision: vi.fn(), listNotebookAssets: vi.fn().mockResolvedValue([]),
    listNotebookUploadBatches: vi.fn().mockResolvedValue([]), getNotebookUploadBatch: vi.fn(),
    closeNotebookUploadBatch: vi.fn(), getNotebookGenerationJob: vi.fn(),
    listNotebookAssetJobs: vi.fn().mockResolvedValue([]), retryMaterial: vi.fn(),
    retryNotebookGenerationJob: vi.fn(), retryAssetParse: vi.fn(), uploadNotebookAsset: vi.fn(),
    useAssetInline: vi.fn(),
  },
}))

const outline = { id: 'book', course_id: 'course', title: '一元微积分', tree_slot: 0, order_revision: 0, chapters: [], historical_sections: [], removed_chapters: [] }
const content = {
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 1, blockId: 'heading' }, content: [{ type: 'text', text: '极限与连续' }] },
    { type: 'paragraph', attrs: { blockId: 'body' }, content: [
      { type: 'text', text: '原来的正文' },
      { type: 'text', text: '加粗内容', marks: [{ type: 'bold' }] },
    ] },
  ],
}
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
  vi.mocked(api.getNotebookDocument).mockResolvedValue({
    schema_version: 2, content, blocks: [], revision: 2, updated_at: '2026-10-20',
  } as never)
  vi.mocked(api.saveNotebookDocument).mockImplementation(async (_course, _book, next, revision) => ({
    schema_version: 2, content: next, blocks: [], revision: revision + 1, updated_at: '2026-10-20',
  }))
  vi.mocked(api.listNotebookRevisions).mockResolvedValue([])
})
afterEach(cleanup)

test('shows course ownership, rich document and generated outline', async () => {
  mount()
  expect(await screen.findByRole('textbox', { name: '笔记名称' })).toHaveProperty('value', '一元微积分')
  expect(screen.getAllByText('数学分析（上）').length).toBeGreaterThan(0)
  await waitFor(() => expect(screen.getByRole('navigation', { name: '笔记目录' }).textContent).toContain('极限与连续'))
  const editor = document.querySelector('.nb-prosemirror') as HTMLElement
  expect(editor.textContent).toContain('原来的正文')
  expect(editor.querySelector('strong')?.textContent).toBe('加粗内容')
  expect(screen.getByRole('button', { name: /课程资料/ }).getAttribute('aria-expanded')).toBe('true')
  expect(screen.getByRole('button', { name: /笔记目录/ }).getAttribute('aria-expanded')).toBe('true')
})

test('resource and outline groups collapse; upload targets the current notebook', async () => {
  const { uploadMaterial, refreshCurrentMaterials } = mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  await waitFor(() => expect(screen.getByRole('navigation', { name: '笔记目录' })).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: /笔记目录/ }))
  expect(screen.queryByRole('navigation', { name: '笔记目录' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /笔记目录/ }))
  expect(screen.getByRole('navigation', { name: '笔记目录' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('选择课程资料'), { target: { files: [new File(['sample'], '第一讲.pdf', { type: 'application/pdf' })] } })
  await waitFor(() => expect(uploadMaterial).toHaveBeenCalledWith(expect.any(File), '第一讲', 'book', '', false, expect.any(String)))
  await waitFor(() => expect(refreshCurrentMaterials).toHaveBeenCalled())
})

test('document save status starts from the server revision', async () => {
  mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  expect(screen.getByRole('status').textContent).toContain('已保存')
  expect(api.saveNotebookDocument).not.toHaveBeenCalled()
})

test('an edited title is not reported as saved', async () => {
  mount()
  const title = await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.change(title, { target: { value: '新的笔记名称' } })
  expect(screen.getByRole('status').textContent).toContain('名称待保存')
})

test('existing sections cannot overwrite a document that already has body text', async () => {
  vi.mocked(api.getNotebookById).mockResolvedValue({
    ...outline, chapters: [{ id: 'chapter', title: '第一章', sections: [{ id: 'section' }] }],
  } as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue({
    schema_version: 2,
    content: { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'body' }, content: [{ type: 'text', text: '已经写好的正文' }] }] },
    blocks: [], revision: 2, updated_at: '2026-10-20',
  } as never)
  mount()
  expect(await screen.findByRole('textbox', { name: '笔记名称' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '导入已有分节笔记' })).toBeNull()
})
