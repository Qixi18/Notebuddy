import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { clearDraft } from '../src/features/notebook-editor/draftStore'
import { NotebookPage } from '../src/pages/NotebookPage'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name = 'ApiError' } },
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

vi.mock('../src/features/notebook-editor/NotebookEditor', async () => {
  const React = await import('react')
  return {
    NotebookEditor: React.forwardRef(function FakeNotebookEditor({ initialContent, onChange, onReady }: {
      initialContent: { type: string; content: unknown[] }
      onChange: (content: unknown) => void
      onReady: (editor: unknown) => void
    }, ref) {
      const content = React.useRef(initialContent)
      const editor = React.useRef({ getJSON: () => content.current })
      React.useImperativeHandle(ref, () => ({
        editor: editor.current,
        replaceContent: (next: typeof initialContent) => { content.current = next },
        focusBlock: () => undefined,
      }))
      React.useEffect(() => { onReady(editor.current) }, [])
      return <button type="button" onClick={() => {
        content.current = { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'edited' }, content: [{ type: 'text', text: '本地新写的正文' }] }] }
        onChange(content.current)
      }}>模拟编辑正文</button>
    }),
  }
})

const outline = {
  id: 'book', course_id: 'course', title: '一元微积分', tree_slot: 0, order_revision: 0,
  chapters: [], historical_sections: [], removed_chapters: [],
}

function mount() {
  const workspace = {
    course: { id: 'course', name: '数学分析（上）' }, materials: [], busy: false,
    uploadMaterial: vi.fn(), refreshCurrentMaterials: vi.fn(), setDocumentDirty: vi.fn(),
  } as unknown as WorkspaceContextValue
  return render(
    <MemoryRouter initialEntries={['/courses/course/notebooks/book']}>
      <WorkspaceProvider value={workspace}>
        <Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes>
      </WorkspaceProvider>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  await clearDraft('course', 'book')
  vi.clearAllMocks()
  vi.mocked(api.getNotebookById).mockResolvedValue(outline as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue({
    schema_version: 2,
    content: { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'p1' }, content: [{ type: 'text', text: '服务器正文' }] }] },
    revision: 4, updated_at: '2026-11-01T10:00:00Z',
  } as never)
  vi.mocked(api.saveNotebookDocument).mockResolvedValue({
    schema_version: 2, content: { type: 'doc', content: [] }, revision: 5,
    updated_at: '2026-11-01T10:05:00Z',
  } as never)
})
afterEach(async () => { cleanup(); await clearDraft('course', 'book'); vi.useRealTimers() })

test('保存遇到 409 时进入冲突态，弹出冲突面板且不静默覆盖', async () => {
  const { ApiError } = await import('../src/api')
  vi.mocked(api.saveNotebookDocument).mockRejectedValue(new ApiError('revision 冲突', 409))

  mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.click(await screen.findByRole('button', { name: '模拟编辑正文' }))
  /* 等保存状态真的变成「待保存」再点保存：避免编辑事件与按钮点击挤在同一帧里 */
  await waitFor(() => expect(screen.getByText(/待保存/)).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))

  await waitFor(() => expect(screen.getByRole('dialog', { name: '保存冲突' })).toBeTruthy())
  expect(screen.getByText(/这篇笔记已在别处更新/)).toBeTruthy()
  // 本地内容仍按「未保存」处理，不能被当成已保存
  expect(screen.queryByText(/^已保存/)).toBeNull()
})

test('冲突里选择「保留本地草稿，暂停自动保存」不会继续写服务器', async () => {
  const { ApiError } = await import('../src/api')
  vi.mocked(api.saveNotebookDocument).mockRejectedValue(new ApiError('revision 冲突', 409))

  mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.click(await screen.findByRole('button', { name: '模拟编辑正文' }))
  /* 等保存状态真的变成「待保存」再点保存：避免编辑事件与按钮点击挤在同一帧里 */
  await waitFor(() => expect(screen.getByText(/待保存/)).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))
  await waitFor(() => expect(screen.getByRole('dialog', { name: '保存冲突' })).toBeTruthy())

  const callsBefore = vi.mocked(api.saveNotebookDocument).mock.calls.length
  fireEvent.click(screen.getByRole('button', { name: '保留本地草稿，暂停自动保存' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '保存冲突' })).toBeNull())
  // 暂停后不再自动重试写服务器
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))
  expect(vi.mocked(api.saveNotebookDocument).mock.calls.length).toBe(callsBefore)
})

test('冲突后可查看服务器版本预览，预览内容来自服务端正文', async () => {
  const { ApiError } = await import('../src/api')
  vi.mocked(api.saveNotebookDocument).mockRejectedValue(new ApiError('revision 冲突', 409))

  mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.click(await screen.findByRole('button', { name: '模拟编辑正文' }))
  /* 等保存状态真的变成「待保存」再点保存：避免编辑事件与按钮点击挤在同一帧里 */
  await waitFor(() => expect(screen.getByText(/待保存/)).toBeTruthy())
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))
  await waitFor(() => expect(screen.getByRole('dialog', { name: '保存冲突' })).toBeTruthy())

  const dialog = screen.getByRole('dialog', { name: '保存冲突' })
  fireEvent.click(within(dialog).getByRole('button', { name: '查看服务器版本' }))
  await waitFor(() => expect(screen.getByRole('dialog', { name: '服务器版本预览' })).toBeTruthy())
  // 初始载入 1 次 + 查看服务器版本至少 1 次
  expect(vi.mocked(api.getNotebookDocument).mock.calls.length).toBeGreaterThanOrEqual(2)
})
