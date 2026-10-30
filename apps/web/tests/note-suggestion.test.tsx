import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { NoteSectionReader } from '../src/features/notes/NoteSectionReader'
import { useNoteSuggestions } from '../src/features/assistant/useNoteSuggestions'
import type { Note } from '../src/types'

const state = vi.hoisted(() => ({ workspace: {} as Record<string, unknown> }))
vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => state.workspace, featurePath: () => '/materials' }))
vi.mock('../src/api', () => ({ ApiError: class ApiError extends Error { status = 0 }, api: {
  getNoteSources: vi.fn().mockResolvedValue([]), getNoteRevisions: vi.fn().mockResolvedValue([]),
  getNoteWebSources: vi.fn().mockResolvedValue([]), listSuggestions: vi.fn().mockResolvedValue([{ id: 's', proposed_markdown: 'suggestion', status: 'pending' }]),
  reviewSuggestion: vi.fn(),
  updateNote: vi.fn(),
  listCourseSuggestions: vi.fn(),
  getNote: vi.fn(),
} }))
afterEach(cleanup)

function SuggestionsHarness({ targets, knownNotes, courseId, refreshNotes }: {
  targets: string[]
  knownNotes: Note[]
  courseId?: string
  refreshNotes: () => Promise<void>
}) {
  const suggestions = useNoteSuggestions({ targets, knownNotes, courseId, refreshNotes })
  return (
    <div>
      <p>pending:{suggestions.suggestions.length}</p>
      <p>{suggestions.notice}</p>
      <button type="button" onClick={() => void suggestions.applyAll()}>apply-all</button>
      {suggestions.suggestions.map((item) => (
        <button key={item.id} type="button" onClick={() => void suggestions.review(item, 'confirm', undefined)}>
          review-{item.id}
        </button>
      ))}
    </div>
  )
}

test('applyAll writes through review only: no stale-revision updateNote (409 regression)', async () => {
  const note = { id: 'n1', course_id: 'c', title: '笔记', content_markdown: '第一行\n第二行', revision_number: 1 } as Note
  vi.mocked(api.listSuggestions).mockResolvedValueOnce([
    { id: 's1', note_id: 'n1', proposed_markdown: '第一行\n第二行\n新增 A', impact: '', status: 'pending' },
    { id: 's2', note_id: 'n1', proposed_markdown: '第一行\n第二行\n新增 A\n新增 B', impact: '', status: 'pending' },
  ])
  // 每次 review(confirm) 服务端都会写笔记并递增 revision，返回更新后的 Note
  vi.mocked(api.reviewSuggestion).mockImplementation((() => {
    return Promise.resolve({ ...note, revision_number: note.revision_number + 1 } as Note)
  }) as never)
  const refreshNotes = vi.fn().mockResolvedValue(undefined)

  render(<SuggestionsHarness targets={['n1']} knownNotes={[note]} refreshNotes={refreshNotes} />)
  await screen.findByText('pending:2')
  fireEvent.click(screen.getByRole('button', { name: 'apply-all' }))

  await screen.findByText('已把 2 条建议写入。')
  expect(vi.mocked(api.updateNote)).not.toHaveBeenCalled()
  expect(refreshNotes).toHaveBeenCalledTimes(1)
})

test('applyAll groups by note: each note diffs against its own content (data-safety red line)', async () => {
  const noteA = { id: 'na', course_id: 'c', title: '甲笔记', content_markdown: 'A 原文', revision_number: 1 } as Note
  const noteB = { id: 'nb', course_id: 'c', title: '乙笔记', content_markdown: 'B 原文', revision_number: 1 } as Note
  vi.mocked(api.listCourseSuggestions).mockResolvedValueOnce([
    { id: 'sa', note_id: 'na', proposed_markdown: 'A 原文\nA 改动', impact: '', status: 'pending', note_title: '甲笔记' },
    { id: 'sb', note_id: 'nb', proposed_markdown: 'B 原文\nB 改动', impact: '', status: 'pending', note_title: '乙笔记' },
  ])
  vi.mocked(api.reviewSuggestion).mockImplementation(((noteId: string) => {
    const base = noteId === 'na' ? noteA : noteB
    return Promise.resolve({ ...base, content_markdown: `${base.content_markdown}\n已写入`, revision_number: 2 } as Note)
  }) as never)
  const refreshNotes = vi.fn().mockResolvedValue(undefined)

  render(<SuggestionsHarness targets={[]} knownNotes={[noteA, noteB]} courseId="c" refreshNotes={refreshNotes} />)
  await screen.findByText('pending:2')
  fireEvent.click(screen.getByRole('button', { name: 'apply-all' }))

  await screen.findByText('已把 2 条建议写入。')
  const calls = vi.mocked(api.reviewSuggestion).mock.calls
  expect(calls.map((call) => call[0])).toEqual(['na', 'nb'])
  /* 红线：A 的建议以 A 的正文为基准，B 以 B 的正文为基准，互相不串 */
  expect(calls[0][4]).toBe('A 原文\nA 改动')
  expect(calls[1][4]).toBe('B 原文\nB 改动')
  expect(String(calls[1][4])).not.toContain('A 改动')
})

test('multi-target suggestions fetch missing note content by id; notice names the target note', async () => {
  const noteB = { id: 'nb', course_id: 'c', title: '乙笔记', content_markdown: 'B 原文', revision_number: 1 } as Note
  vi.mocked(api.listCourseSuggestions).mockResolvedValueOnce([
    { id: 'sb', note_id: 'nb', proposed_markdown: 'B 原文\nB 改动', impact: '整理乙笔记', status: 'pending', note_title: '乙笔记' },
  ])
  vi.mocked(api.getNote).mockResolvedValueOnce(noteB)
  vi.mocked(api.reviewSuggestion).mockResolvedValueOnce({ ...noteB, revision_number: 2 } as Note)
  const refreshNotes = vi.fn().mockResolvedValue(undefined)

  /* knownNotes 只有工作区里的 A；B 不在其中，hook 应按 note_id 自动拉取 */
  render(<SuggestionsHarness targets={[]} knownNotes={[]} courseId="c" refreshNotes={refreshNotes} />)
  await screen.findByText('pending:1')

  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'review-sb' })) })
  await screen.findByText(/已采纳建议，《乙笔记》已更新/)
  expect(vi.mocked(api.reviewSuggestion)).toHaveBeenCalledWith('nb', 'sb', 'confirm', undefined, undefined)
  expect(api.getNote).toHaveBeenCalledWith('nb')
})

test('accepting an earlier suggestion cannot reselect a note after navigation', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api.reviewSuggestion).mockReturnValue(new Promise((done) => { resolve = done }) as never)
  const first = { id: 'n1', course_id: 'c', title: 'First', content_markdown: 'First saved', revision_number: 1 }
  const second = { id: 'n2', course_id: 'c', title: 'Second', content_markdown: 'Second saved', revision_number: 1 }
  const select = vi.fn(), reload = vi.fn(), upsert = vi.fn()
  state.workspace = { courseId: 'c', notes: [first, second], selectedNote: first, setSelectedNoteId: select, reloadNote: reload, upsertNotes: upsert, materials: [], setError: vi.fn(), noteDirty: false, noteSaving: false }
  const page = (id: string) => <MemoryRouter initialEntries={['/courses/c/notebook']}><Routes><Route path="/courses/:courseId/notebook" element={<NoteSectionReader noteId={id} />} /></Routes></MemoryRouter>
  const { rerender } = render(page('n1'))
  fireEvent.click(await screen.findByRole('button', { name: '接受并生成版本' }))
  state.workspace = { ...state.workspace, selectedNote: second, noteDirty: true }
  rerender(page('n2'))
  await act(async () => { resolve({ ...first, content_markdown: 'suggestion', revision_number: 2 }) })
  expect(select).not.toHaveBeenCalledWith('n1')
  expect(reload).not.toHaveBeenCalled()
})
