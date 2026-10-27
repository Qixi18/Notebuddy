import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NotebookEditSuggestion } from '../src/types'

const apiState = vi.hoisted(() => ({
  listNotebookEditSuggestions: vi.fn(),
  reviewNotebookEditSuggestion: vi.fn(),
}))
vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status: number) { super(message) } },
  api: apiState,
}))

import { useNotebookEditSuggestions } from '../src/features/assistant/useNotebookEditSuggestions'

const suggestion: NotebookEditSuggestion = {
  id: 'suggestion-1', notebook_id: 'book-1', base_revision: 4,
  rationale: '补充本节定义', operations: [{ op: 'append', content: '定义内容' }],
  proposed_content: { type: 'doc', content: [] }, status: 'pending',
  created_at: '2026-10-27T00:00:00Z', reviewed_at: null,
}
const content = { type: 'doc', content: [{ type: 'paragraph', attrs: { blockId: 'p1' } }] }

function Harness({ dirty = false, revision = 4 }: { dirty?: boolean; revision?: number }) {
  const state = useNotebookEditSuggestions({ target: {
    courseId: 'course-1', notebookId: 'book-1', title: '极限笔记', revision,
    editVersion: 7, isDirty: () => dirty,
    adoptDocument: vi.fn(() => true),
  } })
  const item = state.suggestions[0]
  return <section>
    <output>{state.notice}</output>
    <button type="button" disabled={!item || Boolean(state.busyId)} onClick={() => item && void state.review(item, 'accept', [0])}>采纳所选操作</button>
  </section>
}

afterEach(() => { cleanup(); vi.clearAllMocks() })

test('dirty Notebook content blocks acceptance without calling the review API', async () => {
  apiState.listNotebookEditSuggestions.mockResolvedValue([suggestion])
  render(<Harness dirty />)
  fireEvent.click(await screen.findByRole('button', { name: '采纳所选操作' }))
  expect(await screen.findByText('当前笔记有未保存修改。请先保存正文，再确认这条建议。')).toBeTruthy()
  expect(apiState.reviewNotebookEditSuggestion).not.toHaveBeenCalled()
})

test('review uses the base revision and selected operation indexes', async () => {
  apiState.listNotebookEditSuggestions.mockResolvedValue([suggestion])
  apiState.reviewNotebookEditSuggestion.mockResolvedValue({
    content, revision: 5, updated_at: '2026-10-27T00:01:00Z',
  })
  render(<Harness />)
  fireEvent.click(await screen.findByRole('button', { name: '采纳所选操作' }))
  await waitFor(() => expect(apiState.reviewNotebookEditSuggestion).toHaveBeenCalledWith(
    'book-1', 'suggestion-1', 'accept', 4, [0],
  ))
  expect(await screen.findByText('已将建议写入《极限笔记》，并生成新的正文修订。')).toBeTruthy()
})

test('stale suggestions are rejected before the review API call', async () => {
  apiState.listNotebookEditSuggestions.mockResolvedValue([suggestion])
  render(<Harness revision={5} />)
  fireEvent.click(await screen.findByRole('button', { name: '采纳所选操作' }))
  expect(await screen.findByText('正文版本已变化，请刷新后重新生成建议。')).toBeTruthy()
  expect(apiState.reviewNotebookEditSuggestion).not.toHaveBeenCalled()
})
