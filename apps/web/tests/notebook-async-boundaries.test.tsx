import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { NotebookPage } from '../src/pages/NotebookPage'

vi.mock('../src/api', () => ({ api: {
  getNotebookById: vi.fn(), getNotebookDocument: vi.fn(), getNotebookChapter: vi.fn(),
  saveNotebookDocument: vi.fn(), listNotebookRevisions: vi.fn(),
  getReadingPosition: vi.fn().mockResolvedValue(null), putReadingPosition: vi.fn().mockResolvedValue({ revision: 1 }),
  listNotebookAssets: vi.fn().mockResolvedValue([]), listDetachedNotebookAssets: vi.fn().mockResolvedValue([]), listNotebookUploadBatches: vi.fn().mockResolvedValue([]),
  getNotebookUploadBatch: vi.fn(), getNotebookGenerationJob: vi.fn(), listNotebookAssetJobs: vi.fn().mockResolvedValue([]),
  listDeletedMaterials: vi.fn().mockResolvedValue([]),
} }))

const { replaceContent } = vi.hoisted(() => ({ replaceContent: vi.fn() }))
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
        replaceContent: (next: typeof initialContent) => { replaceContent(next); content.current = next },
      }))
      React.useEffect(() => { onReady(editor.current) }, [])
      return <button type="button" onClick={() => {
        content.current = { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'edited' }, content: [{ type: 'text', text: '新写正文' }] }] }
        onChange(content.current)
      }}>模拟编辑正文</button>
    }),
  }
})

const empty = { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'empty' }, content: [] }] }

function mount() {
  const workspace = {
    course: { id: 'course', name: '物理学' }, materials: [], busy: false,
    uploadMaterial: vi.fn(), refreshCurrentMaterials: vi.fn(), setDocumentDirty: vi.fn(),
  } as unknown as WorkspaceContextValue
  return render(<MemoryRouter initialEntries={['/courses/course/notebooks/a']}>
    <WorkspaceProvider value={workspace}>
      <Link to="/courses/course/notebooks/b">切换笔记</Link>
      <Routes><Route path="/courses/:courseId/notebooks/:notebookId" element={<NotebookPage />} /></Routes>
    </WorkspaceProvider>
  </MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getNotebookById).mockImplementation(async (_course, book) => ({
    id: book, course_id: 'course', title: book === 'a' ? '笔记 A' : '笔记 B',
    chapters: book === 'a' ? [{ id: 'chapter', title: '第一章', sections: [{ id: 'section' }] }] : [],
    historical_sections: [], removed_chapters: [],
  }) as never)
  vi.mocked(api.getNotebookDocument).mockImplementation(async (_course, book) => ({
    schema_version: 2, content: empty, blocks: [], revision: book === 'a' ? 1 : 7,
    updated_at: '2026-10-24T10:00:00Z',
  }) as never)
  vi.mocked(api.listNotebookRevisions).mockResolvedValue([])
})
afterEach(() => { cleanup(); vi.useRealTimers() })

test('generation completion preserves an unsaved local Notebook draft', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const batch = {
    id: 'batch-1', status: 'generating', inputs: [],
    generation_jobs: [{ id: 'generation-1', status: 'processing' }],
  }
  vi.mocked(api.listNotebookUploadBatches).mockResolvedValue([batch] as never)
  vi.mocked(api.getNotebookUploadBatch).mockResolvedValue(batch as never)
  vi.mocked(api.getNotebookGenerationJob)
    .mockResolvedValueOnce({ id: 'generation-1', status: 'processing' } as never)
    .mockResolvedValueOnce({ id: 'generation-1', status: 'completed' } as never)
  mount()
  await waitFor(() => expect(api.getNotebookGenerationJob).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('button', { name: '模拟编辑正文' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(screen.getByText(/当前有未保存的本地编辑，已保留草稿/)).toBeTruthy()
  expect(replaceContent).not.toHaveBeenCalled()
})

test('a save response from the previous notebook cannot change the next notebook revision', async () => {
  let finishOldSave!: (value: unknown) => void
  vi.mocked(api.saveNotebookDocument).mockImplementationOnce(() => new Promise((resolve) => { finishOldSave = resolve }))
    .mockImplementation(async (_course, _book, content, revision) => ({
      schema_version: 2, content, blocks: [], revision: revision + 1, updated_at: '2026-10-24T10:01:00Z',
    }) as never)
  mount()
  await screen.findByRole('textbox', { name: '笔记名称' })
  fireEvent.click(screen.getByRole('button', { name: '模拟编辑正文' }))
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))
  await waitFor(() => expect(api.saveNotebookDocument).toHaveBeenCalledWith('course', 'a', expect.anything(), 1))
  fireEvent.click(screen.getByRole('link', { name: '切换笔记' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: '笔记名称' })).toHaveProperty('value', '笔记 B'))
  await act(async () => {
    finishOldSave({ schema_version: 2, content: empty, blocks: [], revision: 2, updated_at: '2026-10-24T10:02:00Z' })
  })
  fireEvent.click(screen.getByRole('button', { name: '模拟编辑正文' }))
  await waitFor(() => expect(document.querySelector('.notebook-document-save-status')?.textContent).toContain('待保存'))
  fireEvent.click(screen.getByRole('button', { name: '立即保存' }))
  await waitFor(() => expect(api.saveNotebookDocument).toHaveBeenCalledWith('course', 'b', expect.anything(), 7))
})
