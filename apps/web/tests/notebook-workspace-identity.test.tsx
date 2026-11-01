import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { notebookApiAdapter } from '../src/features/notebook-workspace/adapters/notebookApiAdapter'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status: number) { super(message) } },
  api: {
    getNotebookById: vi.fn(), getNotebookDocument: vi.fn(), saveNotebookDocument: vi.fn(),
    getUnboundNotebook: vi.fn(), getUnboundNotebookDocument: vi.fn(), saveUnboundNotebookDocument: vi.fn(),
    renameNotebook: vi.fn(), renameUnboundNotebook: vi.fn(),
    listNotebookAssets: vi.fn().mockResolvedValue([]), listDetachedNotebookAssets: vi.fn().mockResolvedValue([]),
    listNotebookUploadBatches: vi.fn().mockResolvedValue([]), listNotebookAssetJobs: vi.fn().mockResolvedValue([]),
    listDeletedMaterials: vi.fn().mockResolvedValue([]),
    getReadingPosition: vi.fn().mockResolvedValue(null), putReadingPosition: vi.fn().mockResolvedValue({ revision: 1 }),
    uploadNotebookAttachment: vi.fn(), listNotebookRevisions: vi.fn().mockResolvedValue([]),
  },
}))

const outline = {
  id: 'book', course_id: 'course', title: '一元微积分', tree_slot: 0, order_revision: 0,
  chapters: [], historical_sections: [], removed_chapters: [],
}

function mount(path: string) {
  const workspace = {
    course: { id: 'course', name: '数学分析（上）' }, materials: [], busy: false,
    uploadMaterial: vi.fn(), refreshCurrentMaterials: vi.fn(), setDocumentDirty: vi.fn(),
  } as unknown as WorkspaceContextValue
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceProvider value={workspace}>
        <Routes>
          <Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} />
          <Route path="/notebooks/unbound/:notebookId" element={<NotebookPage />} />
        </Routes>
      </WorkspaceProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebookById).mockResolvedValue(outline as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue({
    schema_version: 2, content: { type: 'doc', content: [] }, revision: 3,
    updated_at: '2026-11-01T10:00:00Z',
  } as never)
  vi.mocked(api.getUnboundNotebook).mockResolvedValue({
    id: 'solo', title: '未分类笔记', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z',
  } as never)
  vi.mocked(api.getUnboundNotebookDocument).mockResolvedValue({
    schema_version: 2, content: { type: 'doc', content: [] }, revision: 5,
    updated_at: '2026-11-01T10:00:00Z',
  } as never)
})
afterEach(cleanup)

test('课程 Notebook 用课程路由读取正文', async () => {
  mount('/courses/course/notebooks/book')
  expect(await screen.findByRole('textbox', { name: '笔记名称' })).toHaveProperty('value', '一元微积分')
  expect(api.getNotebookById).toHaveBeenCalledWith('course', 'book')
  expect(api.getNotebookDocument).toHaveBeenCalledWith('course', 'book')
  expect(api.getUnboundNotebook).not.toHaveBeenCalled()
})

test('未分类 Notebook 用 unbound 路由读取，且不伪造课程 ID', async () => {
  mount('/notebooks/unbound/solo')
  expect(await screen.findByRole('textbox', { name: '笔记名称' })).toHaveProperty('value', '未分类笔记')
  expect(api.getUnboundNotebook).toHaveBeenCalledWith('solo')
  expect(api.getUnboundNotebookDocument).toHaveBeenCalledWith('solo')
  // 不能因为「未分类」就去调课程级接口
  expect(api.getNotebookById).not.toHaveBeenCalled()
  expect(api.getNotebookDocument).not.toHaveBeenCalled()
  expect(api.listDeletedMaterials).not.toHaveBeenCalled()
  expect(screen.getAllByText(/未分类/).length).toBeGreaterThan(0)
})

test('adapter 用 null 表达无课程归属，而不是字符串 unbound', () => {
  const course = notebookApiAdapter({ kind: 'course', courseId: 'c1', notebookId: 'n1' })
  const unbound = notebookApiAdapter({ kind: 'unbound', notebookId: 'n1' })
  expect(course.courseId).toBe('c1')
  expect(unbound.courseId).toBeNull()
  expect(unbound.identity).toEqual({ kind: 'unbound', notebookId: 'n1' })
})

test('两条路由共用同一个 Workspace 组件（不复活 UnboundNotebookPage）', async () => {
  const courseView = mount('/courses/course/notebooks/book')
  await screen.findByRole('textbox', { name: '笔记名称' })
  expect(courseView.container.querySelector('.notebook-document-page')).toBeTruthy()
  cleanup()
  const unboundView = mount('/notebooks/unbound/solo')
  await waitFor(() => expect(screen.getByRole('textbox', { name: '笔记名称' })).toBeTruthy())
  expect(unboundView.container.querySelector('.notebook-document-page')).toBeTruthy()
})
