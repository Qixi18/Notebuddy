import { act, cleanup, fireEvent, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../src/api'
import type { NotebookEditorHandle } from '../src/features/notebook-editor/NotebookEditor'
import { useDocumentReadingPosition } from '../src/features/notebook-editor/useDocumentReadingPosition'

function fakeEditor(blockId = 'heading-a') {
  const root = document.createElement('div')
  const block = document.createElement('h2')
  block.setAttribute('data-block-id', blockId)
  block.getBoundingClientRect = () => ({
    x: 0, y: 50, width: 100, height: 100, top: 50, right: 100, bottom: 150, left: 0, toJSON: () => ({}),
  }) as DOMRect
  root.append(block)
  document.body.append(root)
  const focusBlock = vi.fn()
  const handle = { editor: { view: { dom: root } }, focusBlock } as unknown as NotebookEditorHandle
  return { root, ref: { current: handle }, focusBlock }
}

function position(overrides: Record<string, unknown> = {}) {
  return {
    notebook_id: 'book-a', chapter_id: null, note_id: null, block_id: 'heading-a',
    mode: 'book' as const, section_offset: 0.25, revision: 4, updated_at: '2026-10-29T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => { cleanup(); vi.useRealTimers(); document.body.replaceChildren() })

test('restores only a live stable block ID', async () => {
  const editor = fakeEditor()
  vi.spyOn(api, 'getReadingPosition').mockResolvedValue(position())
  const restore = vi.fn()
  const frame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { callback(0); return 1 })
  renderHook(() => useDocumentReadingPosition({
    courseId: 'course-a', notebookId: 'book-a', editorRef: editor.ref,
    ready: true, explicitLink: false, onRestore: restore,
  }))
  await waitFor(() => expect(editor.focusBlock).toHaveBeenCalledWith('heading-a'))
  expect(restore).toHaveBeenCalledWith('heading-a')
  expect(frame).toHaveBeenCalled()
})

test('an explicit deep link suppresses bookmark restoration', async () => {
  const editor = fakeEditor()
  vi.spyOn(api, 'getReadingPosition').mockResolvedValue(position())
  renderHook(() => useDocumentReadingPosition({
    courseId: 'course-a', notebookId: 'book-a', editorRef: editor.ref,
    ready: true, explicitLink: true, onRestore: vi.fn(),
  }))
  await waitFor(() => expect(api.getReadingPosition).toHaveBeenCalledWith('course-a', 'book-a'))
  await act(async () => { await Promise.resolve() })
  expect(editor.focusBlock).not.toHaveBeenCalled()
})

test('debounces a block bookmark and writes with the reading-position revision', async () => {
  vi.useFakeTimers()
  const editor = fakeEditor()
  vi.spyOn(api, 'getReadingPosition').mockResolvedValue(position())
  const put = vi.spyOn(api, 'putReadingPosition').mockResolvedValue(position({ revision: 5 }))
  renderHook(() => useDocumentReadingPosition({
    courseId: 'course-a', notebookId: 'book-a', editorRef: editor.ref,
    ready: true, explicitLink: true, onRestore: vi.fn(),
  }))
  await act(async () => { await Promise.resolve() })
  fireEvent.scroll(document)
  await act(async () => { await vi.advanceTimersByTimeAsync(649) })
  expect(put).not.toHaveBeenCalled()
  await act(async () => { await vi.advanceTimersByTimeAsync(1); await Promise.resolve() })
  expect(put).toHaveBeenCalledWith('course-a', 'book-a', {
    chapter_id: null, note_id: null, block_id: 'heading-a', mode: 'book',
    section_offset: 0.3, expected_revision: 4,
  })
})

test('unmount flushes a pending save to the old Notebook scope', async () => {
  const editor = fakeEditor()
  vi.spyOn(api, 'getReadingPosition').mockResolvedValue(null)
  const put = vi.spyOn(api, 'putReadingPosition').mockResolvedValue(position({ revision: 1 }))
  const { unmount } = renderHook(() => useDocumentReadingPosition({
    courseId: 'course-a', notebookId: 'book-a', editorRef: editor.ref,
    ready: true, explicitLink: true, onRestore: vi.fn(),
  }))
  await waitFor(() => expect(api.getReadingPosition).toHaveBeenCalledWith('course-a', 'book-a'))
  await act(async () => { await Promise.resolve() })
  fireEvent.scroll(document)
  unmount()
  await waitFor(() => expect(put).toHaveBeenCalledWith('course-a', 'book-a', expect.objectContaining({
    block_id: 'heading-a', expected_revision: 0,
  })))
})

test('a 409 stops further bookmark writes until the Notebook is reloaded', async () => {
  vi.useFakeTimers()
  const editor = fakeEditor()
  vi.spyOn(api, 'getReadingPosition').mockResolvedValue(position())
  const put = vi.spyOn(api, 'putReadingPosition').mockRejectedValue(new ApiError('conflict', 409))
  renderHook(() => useDocumentReadingPosition({
    courseId: 'course-a', notebookId: 'book-a', editorRef: editor.ref,
    ready: true, explicitLink: true, onRestore: vi.fn(),
  }))
  await act(async () => { await Promise.resolve() })
  fireEvent.scroll(document)
  await act(async () => { await vi.advanceTimersByTimeAsync(650) })
  await act(async () => { await Promise.resolve() })
  fireEvent.scroll(document)
  await act(async () => { await vi.advanceTimersByTimeAsync(650) })
  expect(put).toHaveBeenCalledTimes(1)
})
