import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { api, ApiError } from '../src/api'
import { useNotebookSave } from '../src/features/notebook-editor/useNotebookSave'
import type { DocNode } from '../src/features/notebook-editor/document'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) { super(message); this.status = status }
  },
  api: {
    saveNotebookDocument: vi.fn(),
    getNotebookDocument: vi.fn(),
  },
}))

const base: DocNode = {
  type: 'doc',
  content: [{ type: 'paragraph', attrs: { blockId: 'p' }, content: [{ type: 'text', text: '第一版' }] }],
}
const edited: DocNode = {
  type: 'doc',
  content: [{ type: 'paragraph', attrs: { blockId: 'p' }, content: [{ type: 'text', text: '第二版' }] }],
}
const editedAgain: DocNode = {
  type: 'doc',
  content: [{ type: 'paragraph', attrs: { blockId: 'p' }, content: [{ type: 'text', text: '保存期间继续输入' }] }],
}

function savedResponse(content: DocNode, revision: number) {
  return { schema_version: 2, content, blocks: [], revision, updated_at: '2026-10-24T10:00:00Z' }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  vi.mocked(api.saveNotebookDocument).mockImplementation(async (_course, _book, content, revision) => savedResponse(content, revision + 1))
})
afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
})

describe('useNotebookSave', () => {
  test('debounces edits and confirms only the saved snapshot', async () => {
    const { result } = renderHook(() => useNotebookSave({ courseId: 'course', notebookId: 'book' }))
    act(() => result.current.reset(base, 1, '2026-10-24T09:00:00Z'))
    expect(result.current.state).toBe('saved')

    act(() => result.current.markEdited(edited))
    expect(result.current.state).toBe('unsaved')
    expect(api.saveNotebookDocument).not.toHaveBeenCalled()

    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    expect(api.saveNotebookDocument).toHaveBeenCalledWith('course', 'book', edited, 1)
    expect(result.current.state).toBe('saved')
    expect(result.current.revision).toBe(2)
  })

  test('stops autosave on 409, keeps the local draft and allows explicit overwrite', async () => {
    vi.mocked(api.saveNotebookDocument).mockRejectedValueOnce(new ApiError('stale', 409))
    const { result } = renderHook(() => useNotebookSave({ courseId: 'course', notebookId: 'book' }))
    act(() => result.current.reset(base, 1))
    act(() => result.current.markEdited(edited))
    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    expect(result.current.state).toBe('conflict')
    expect(result.current.conflictOpen).toBe(true)

    act(() => result.current.markEdited({ ...edited, content: [...(edited.content ?? [])] }))
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    expect(api.saveNotebookDocument).toHaveBeenCalledTimes(1)

    vi.mocked(api.getNotebookDocument).mockResolvedValue(savedResponse(base, 5))
    vi.mocked(api.saveNotebookDocument).mockImplementation(async (_course, _book, content, revision) => savedResponse(content, revision + 1))
    await act(async () => { await result.current.overwriteServer() })
    expect(api.getNotebookDocument).toHaveBeenCalledWith('course', 'book')
    expect(api.saveNotebookDocument).toHaveBeenLastCalledWith('course', 'book', expect.anything(), 5)
    expect(result.current.state).toBe('saved')
  })

  test('a 409 keeps the local draft recoverable while the server append can be previewed', async () => {
    vi.mocked(api.saveNotebookDocument).mockRejectedValueOnce(new ApiError('stale', 409))
    const serverAppend = {
      ...base,
      content: [...(base.content ?? []), {
        type: 'paragraph', attrs: { blockId: 'ai-added' },
        content: [{ type: 'text', text: '服务器新增的 AI 内容' }],
      }],
    }
    vi.mocked(api.getNotebookDocument).mockResolvedValue(savedResponse(serverAppend, 2))
    const { result } = renderHook(() => useNotebookSave({ courseId: 'course', notebookId: 'book' }))
    act(() => result.current.reset(base, 1))
    act(() => result.current.markEdited(edited))

    await act(async () => { await result.current.saveNow() })
    expect(result.current.state).toBe('conflict')
    const latest = await result.current.fetchServer()
    expect(latest?.content.content?.at(-1)).toMatchObject({
      attrs: { blockId: 'ai-added' },
    })
    expect(JSON.stringify(latest?.content)).toContain('服务器新增的 AI 内容')

    act(() => result.current.keepLocalDraft())
    await act(async () => { await Promise.resolve() })
    expect(result.current.state).toBe('unsaved')
    expect(result.current.conflictOpen).toBe(false)
    expect(localStorage.getItem('notebuddy-draft:notebook:course:book')).toContain('第二版')
    expect(api.saveNotebookDocument).toHaveBeenCalledTimes(1)
  })

  test('keeps the latest recovery draft while an older snapshot finishes saving', async () => {
    let completeSave!: (response: ReturnType<typeof savedResponse>) => void
    vi.mocked(api.saveNotebookDocument).mockImplementationOnce(() => new Promise((resolve) => { completeSave = resolve }))
    const { result } = renderHook(() => useNotebookSave({ courseId: 'course', notebookId: 'book' }))
    act(() => result.current.reset(base, 1))
    act(() => result.current.markEdited(edited))
    await act(async () => { await vi.advanceTimersByTimeAsync(900) })
    act(() => result.current.markEdited(editedAgain))
    await act(async () => { await vi.advanceTimersByTimeAsync(550) })
    await act(async () => { completeSave(savedResponse(edited, 2)); await Promise.resolve() })
    await act(async () => { await Promise.resolve() })
    expect(result.current.state).toBe('unsaved')
    expect(localStorage.getItem('notebuddy-draft:notebook:course:book')).toContain('保存期间继续输入')
  })
})
