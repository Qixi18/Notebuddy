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
    getUnboundNotebook: vi.fn(), getUnboundNotebookDocument: vi.fn(), saveUnboundNotebookDocument: vi.fn(),
    renameNotebook: vi.fn(),
    listNotebookAssets: vi.fn().mockResolvedValue([]), listDetachedNotebookAssets: vi.fn().mockResolvedValue([]),
    listNotebookUploadBatches: vi.fn().mockResolvedValue([]), listNotebookAssetJobs: vi.fn().mockResolvedValue([]),
    listDeletedMaterials: vi.fn().mockResolvedValue([]),
    getReadingPosition: vi.fn().mockResolvedValue(null), putReadingPosition: vi.fn().mockResolvedValue({ revision: 1 }),
    uploadNotebookAttachment: vi.fn(), listNotebookRevisions: vi.fn().mockResolvedValue([]),
  },
}))

const courseOutline = {
  id: 'book', course_id: 'course', title: '课程笔记', tree_slot: 0, order_revision: 0,
  chapters: [], historical_sections: [], removed_chapters: [],
}

function mount(path: string) {
  const uploadMaterial = vi.fn().mockResolvedValue(undefined)
  const workspace = {
    course: { id: 'course', name: '数学分析（上）' }, materials: [], busy: false,
    uploadMaterial, refreshCurrentMaterials: vi.fn().mockResolvedValue(undefined), setDocumentDirty: vi.fn(),
  } as unknown as WorkspaceContextValue
  render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceProvider value={workspace}>
        <Routes>
          <Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} />
          <Route path="/notebooks/unbound/:notebookId" element={<NotebookPage />} />
        </Routes>
      </WorkspaceProvider>
    </MemoryRouter>,
  )
  return { uploadMaterial }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebookById).mockResolvedValue(courseOutline as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue({
    schema_version: 2, content: { type: 'doc', content: [] }, revision: 1,
    updated_at: '2026-11-01T10:00:00Z',
  } as never)
  vi.mocked(api.getUnboundNotebook).mockResolvedValue({
    id: 'solo', title: '未分类笔记', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z',
  } as never)
  vi.mocked(api.getUnboundNotebookDocument).mockResolvedValue({
    schema_version: 2, content: { type: 'doc', content: [] }, revision: 2,
    updated_at: '2026-11-01T10:00:00Z',
  } as never)
})
afterEach(cleanup)

test('课程 Notebook 的资料上传走课程资料控件，并带上当前 notebookId', async () => {
  const { uploadMaterial } = mount('/courses/course/notebooks/book')
  await screen.findByRole('textbox', { name: '笔记名称' })
  expect(screen.getByLabelText('选择课程资料')).toBeTruthy()

  const file = new File(['pdf'], '第一讲.pdf', { type: 'application/pdf' })
  fireEvent.change(screen.getByLabelText('选择课程资料'), { target: { files: [file] } })

  await waitFor(() => expect(uploadMaterial).toHaveBeenCalledWith(
    expect.any(File), '第一讲', 'book', '', false, expect.any(String), undefined,
  ))
})

test('未分类 Notebook 使用资料与生成面板，不复用课程资料上传入口', async () => {
  mount('/notebooks/unbound/solo')
  await screen.findByRole('textbox', { name: '笔记名称' })
  // 未分类走独立的 SourceUploadPanel（自己带 AI 生成状态），不出现课程资料上传控件
  expect(screen.queryByLabelText('选择课程资料')).toBeNull()
  expect(screen.getByLabelText('学习资料与生成状态')).toBeTruthy()
})

test('两类 Notebook 都能上传图片资料（入口不同、能力一致）', async () => {
  mount('/courses/course/notebooks/book')
  await screen.findByRole('textbox', { name: '笔记名称' })
  // 课程 Notebook：侧栏独立的原始图片资料入口
  expect(screen.getByLabelText('选择原始图片资料')).toBeTruthy()

  cleanup()
  mount('/notebooks/unbound/solo')
  await screen.findByRole('textbox', { name: '笔记名称' })
  // 未分类 Notebook：资料与生成面板同一入口，接受 pdf/pptx/docx/png/jpg
  const panel = screen.getByLabelText('学习资料与生成状态')
  expect(panel.textContent).toContain('支持 PDF / PPTX / DOCX / PNG / JPG')
  expect(screen.getByRole('button', { name: '上传 PDF 或图片' })).toBeTruthy()
})
