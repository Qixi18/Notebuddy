import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'
import { UnboundNotebookPage } from '../src/pages/UnboundNotebookPage'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error {},
  api: {
    getNotebookById: vi.fn(), getNotebookDocument: vi.fn(), getUnboundNotebook: vi.fn(), getUnboundNotebookDocument: vi.fn(),
    listNotebookRevisions: vi.fn(), getNotebookRevision: vi.fn(), restoreNotebookRevision: vi.fn(),
    listUnboundNotebookRevisions: vi.fn(), getUnboundNotebookRevision: vi.fn(), restoreUnboundNotebookRevision: vi.fn(),
    listNotebookAssets: vi.fn().mockResolvedValue([]), listDetachedNotebookAssets: vi.fn().mockResolvedValue([]),
    listNotebookUploadBatches: vi.fn().mockResolvedValue([]), listNotebookAssetJobs: vi.fn().mockResolvedValue([]),
    listDeletedMaterials: vi.fn().mockResolvedValue([]), getReadingPosition: vi.fn().mockResolvedValue(null),
    putReadingPosition: vi.fn().mockResolvedValue({ revision: 1 }),
  },
}))

const content = { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'body' }, content: [{ type: 'text', text: '已保存正文' }] }] }
const documentResponse = { schema_version: 2, content, blocks: [], revision: 4, updated_at: '2026-10-30T00:00:00Z' }
const revisions = ['ai_append', 'ai_suggestion', 'restore', 'autosave', 'future-origin'].map((origin, index) => ({ revision: index + 1, origin, created_at: '2026-10-30T00:00:00Z' }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const book = { id: 'history-book', course_id: 'course', title: '历史测试笔记', tree_slot: 0, order_revision: 0, chapters: [], historical_sections: [], removed_chapters: [] }
  vi.mocked(api.getNotebookById).mockResolvedValue(book as never)
  vi.mocked(api.getUnboundNotebook).mockResolvedValue({ ...book, course_id: null } as never)
  vi.mocked(api.getNotebookDocument).mockResolvedValue(documentResponse)
  vi.mocked(api.getUnboundNotebookDocument).mockResolvedValue(documentResponse)
  vi.mocked(api.listNotebookRevisions).mockResolvedValue(revisions)
  vi.mocked(api.listUnboundNotebookRevisions).mockResolvedValue(revisions)
  vi.mocked(api.getNotebookRevision).mockResolvedValue({ ...documentResponse, revision: 1, origin: 'ai_append', created_at: '2026-10-30T00:00:00Z' })
  vi.mocked(api.getUnboundNotebookRevision).mockResolvedValue({ ...documentResponse, revision: 1, origin: 'ai_append', created_at: '2026-10-30T00:00:00Z' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

async function mountNotebook(unbound: boolean, busy = false) {
  const workspace = { course: { id: 'course', name: '课程' }, materials: [], busy, setDocumentDirty: vi.fn(), uploadMaterial: vi.fn(), refreshCurrentMaterials: vi.fn() } as unknown as WorkspaceContextValue
  render(<MemoryRouter initialEntries={[unbound ? '/notebooks/history-book' : '/courses/course/notebooks/history-book']}>
    <WorkspaceProvider value={workspace}><Routes>
      <Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} />
      <Route path="/notebooks/:notebookId" element={<UnboundNotebookPage />} />
    </Routes></WorkspaceProvider>
  </MemoryRouter>)
  await screen.findByDisplayValue('历史测试笔记')
}

async function openHistory(unbound: boolean) {
  await mountNotebook(unbound)
  const opener = screen.getByRole('button', { name: '历史版本', exact: true })
  opener.focus()
  fireEvent.click(opener)
  const dialog = screen.getByRole('dialog', { name: '历史版本' })
  await within(dialog).findByText('revision 1')
  return { dialog, opener }
}

test('an assistant busy state does not change the idle upload label', async () => {
  await mountNotebook(false, true)
  expect(screen.getByRole('button', { name: '上传资料', exact: true })).toHaveProperty('disabled', true)
  expect(screen.queryByText('上传中…')).toBeNull()
})

test.each([false, true])('history moves focus inside, traps Tab, and restores its opener on Escape (unbound=%s)', async unbound => {
  const { dialog, opener } = await openHistory(unbound)
  expect(dialog.contains(document.activeElement)).toBe(true)
  const controls = Array.from(dialog.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
  controls.at(-1)!.focus()
  fireEvent.keyDown(document.activeElement!, { key: 'Tab' })
  expect(document.activeElement).toBe(controls[0])
  fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(controls.at(-1))
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: '历史版本' })).toBeNull()
  expect(document.activeElement).toBe(opener)
})

test.each([false, true])('history labels saved origins without exposing internal tokens (unbound=%s)', async unbound => {
  const { dialog } = await openHistory(unbound)
  for (const label of ['AI 生成', 'AI 修改', '历史恢复', '自动保存', '保存版本']) expect(within(dialog).getByText(label)).toBeTruthy()
})

test.each([false, true])('history stays open during restore and allows retry after failure (unbound=%s)', async unbound => {
  let rejectRestore!: (error: Error) => void
  const restore = unbound ? api.restoreUnboundNotebookRevision : api.restoreNotebookRevision
  vi.mocked(restore).mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRestore = reject }))
  const { dialog, opener } = await openHistory(unbound)
  fireEvent.click(within(dialog).getByText('revision 1'))
  await waitFor(() => expect((within(dialog).getByRole('button', { name: /恢复到此版本/ }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(within(dialog).getByRole('button', { name: /恢复到此版本/ }))
  await waitFor(() => expect(restore).toHaveBeenCalledTimes(1))
  fireEvent.keyDown(dialog, { key: 'Escape' })
  for (const close of within(dialog).getAllByRole('button', { name: '关闭', exact: true })) {
    expect((close as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(close)
  }
  expect(screen.getByRole('dialog', { name: '历史版本' })).toBe(dialog)
  fireEvent.keyDown(dialog, { key: 'Tab' })
  expect(dialog.contains(document.activeElement)).toBe(true)
  await act(async () => rejectRestore(new Error('恢复服务暂不可用')))
  expect(await within(dialog).findByRole('alert')).toHaveProperty('textContent', '恢复服务暂不可用')
  expect((within(dialog).getByRole('button', { name: /恢复到此版本/ }) as HTMLButtonElement).disabled).toBe(false)
  vi.mocked(restore).mockResolvedValueOnce({ ...documentResponse, revision: 5 })
  fireEvent.click(within(dialog).getByRole('button', { name: /恢复到此版本/ }))
  await screen.findByText(unbound ? '已恢复历史版本。' : '已恢复到选中的历史版本，并生成新的修订。')
  expect(restore).toHaveBeenLastCalledWith(...(unbound ? ['history-book', 1, 4] : ['course', 'history-book', 1, 4]))
  expect(screen.queryByRole('dialog', { name: '历史版本' })).toBeNull()
  expect(document.activeElement).toBe(opener)
})
