import { useMemo, useRef } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

const saveMock = vi.hoisted(() => ({
  isDirty: vi.fn(() => false),
  reset: vi.fn(),
  revision: 0,
  state: 'saved' as const,
}))

vi.mock('../src/features/notebook-editor/useNotebookSave', () => ({
  // Match the real hook's API object behavior: wrapper identity is new each render,
  // while its individual methods and primitive state remain stable.
  useNotebookSave: () => ({ ...saveMock }),
}))

import { NotebookBridgeProvider, useRegisterNotebookBridge } from '../src/features/notebook-editor/NotebookBridge'
import { useNotebookDocument } from '../src/features/notebook-workspace/hooks/useNotebookDocument'

const notebookApi = {
  getNotebook: vi.fn(async () => ({
    id: 'book-1', course_id: 'course-1', title: '桥接测试笔记', tree_slot: 0,
    order_revision: 0, processing: false, chapters: [], historical_sections: [], removed_chapters: [],
  })),
  getDocument: vi.fn(async () => ({
    revision: 0, updated_at: '2026-11-03T00:00:00Z',
    content: { type: 'doc' as const, content: [] },
  })),
  rename: vi.fn(),
}

function NotebookBridgeHarness() {
  const editorRef = useRef(null)
  const document = useNotebookDocument({
    notebookId: 'book-1', courseId: 'course-1', notebookApi: notebookApi as never,
    editorRef, onNotice: () => {},
  })
  const bridgeValue = useMemo(() => document.loaded ? {
    courseId: 'course-1', notebookId: 'book-1', title: document.title,
    revision: document.save.revision, editVersion: document.editVersion,
    excerpt: '', selection: null, isDirty: document.save.isDirty,
    adoptDocument: document.adoptDocument, insertAI: () => true,
  } : null, [document.adoptDocument, document.editVersion, document.loaded,
    document.save.isDirty, document.save.revision, document.title])
  useRegisterNotebookBridge(bridgeValue)
  return <p>{document.loaded ? document.title : '正在载入'}</p>
}

afterEach(() => {
  cleanup()
  notebookApi.getNotebook.mockClear()
  notebookApi.getDocument.mockClear()
  saveMock.reset.mockClear()
})

test('Notebook document callback identities settle after bridge registration', async () => {
  render(<NotebookBridgeProvider><NotebookBridgeHarness /></NotebookBridgeProvider>)

  expect(await screen.findByText('桥接测试笔记')).toBeTruthy()
  await waitFor(() => expect(saveMock.reset).toHaveBeenCalledTimes(1))
  // A fresh wrapper object is returned each render; the exposed callbacks must
  // still settle instead of causing the bridge context to write in a loop.
  expect(notebookApi.getNotebook).toHaveBeenCalledTimes(1)
  expect(notebookApi.getDocument).toHaveBeenCalledTimes(1)
})
