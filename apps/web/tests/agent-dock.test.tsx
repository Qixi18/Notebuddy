import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

vi.mock('../src/components/SettingsPanel', () => ({ SettingsPanel: () => null }))
vi.mock('../src/api', () => ({
  api: {
    listMaterials: vi.fn(async () => []),
    getNotebookDocument: vi.fn(async () => ({ revision: 3, blocks: [{ text: 'Notebook 当前正文' }] })),
  },
}))

import { api } from '../src/api'
import { AppLayout, WorkspaceProvider } from '../src/components/AppLayout'
import { DOCK_STORAGE } from '../src/features/assistant/dockLayout'
import type { AgentRunState } from '../src/features/conversation/useConversation'

afterEach(cleanup)
beforeEach(() => { localStorage.clear() })

const course = { id: 'c1', name: '线性代数', created_at: '2026-01-01T00:00:00Z' }
const note = {
  id: 'n1', course_id: 'c1', title: '行列式笔记', content_markdown: '# 行列式\n已有正文。',
  material_id: null, section_key: '行列式', section_order: 0, knowledge_node_id: 'k1',
  content_origin: 'user', user_locked: false, revision_number: 1,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const askAgent = vi.fn(async () => true)

function liveRun(overrides: Partial<AgentRunState> = {}): AgentRunState {
  return { steps: [], streamingText: '', ...overrides }
}

function renderShell(overrides: Record<string, unknown> = {}) {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  const workspace = {
    courseId: 'c1',
    course,
    courses: [course],
    conversationCourseId: 'c1',
    materials: [],
    selectedNote: note,
    noteDirty: false,
    noteSaving: false,
    openMaterialSource: () => {},
    refreshCurrentNotes: vi.fn(async () => {}),
    teacherPersona: 'elf',
    error: undefined,
    setError: () => {},
    ...overrides,
    conversation: {
      messages: [], conversations: [], conversationId: undefined, hasMessages: false,
      busy: false, error: undefined, agentRun: null,
      ask: async () => true, askAgent, startNewConversation: async () => {},
      ...(overrides.conversation as Record<string, unknown> | undefined),
    },
  } as never
  const router = createMemoryRouter(
    [{ path: '/courses/:courseId/notebooks/:notebookId', element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider> }, { path: '*', element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider> }],
    { initialEntries: ['/courses/c1/notebook'] },
  )
  render(<RouterProvider router={router} />)
}

function scopeSelect() {
  return screen.getByLabelText(/本次提问的作用范围/) as HTMLSelectElement
}

test('笔记本编辑器提供选区采纳提示，助手发送课程范围并携带 Notebook 上下文', async () => {
  renderShell()
  const select = scopeSelect()
  const options = Array.from(select.options).map((option) => option.value)
  expect(options).not.toContain('__note__')
  expect(options).toContain('__global__')

  fireEvent.change(screen.getByLabelText(/快速提问/), { target: { value: '帮我整理这一节' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0]?.[0]).toBe('帮我整理这一节')
  expect(askAgent.mock.calls[0]?.[1].scope).toBe('course')
  expect(askAgent.mock.calls[0]?.[1].notebookContext).toBeUndefined()
  expect(askAgent.mock.calls[0]?.[1].readingContext?.excerpt).toBeUndefined()
})

test('全局档不带笔记节选，scope 传 global', async () => {
  renderShell()
  fireEvent.change(scopeSelect(), { target: { value: '__global__' } })
  fireEvent.change(screen.getByLabelText(/快速提问/), { target: { value: '别的课程里有相关内容吗' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  const options = askAgent.mock.calls[0]?.[1]
  expect(options.scope).toBe('global')
  expect(options.notebookContext).toBeUndefined()
})

test('agent 执行中显示步骤时间线与流式文本', () => {
  const agentRun = liveRun({
    steps: [
      { type: 'step', tool: 'search_course', detail: '检索「行列式」', status: 'running' },
      { type: 'step', tool: 'search_course', detail: '命中 2 条课件片段', status: 'done' },
    ],
    streamingText: '行列式是线性代数的基本工具',
  })
  renderShell({ conversation: {
    messages: [], busy: true, error: undefined, agentRun,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(screen.getByText(/检索课程课件/)).toBeTruthy()
  expect(screen.getByText(/命中 2 条课件片段/)).toBeTruthy()
  expect(screen.getByText(/行列式是线性代数的基本工具/)).toBeTruthy()
  expect(document.querySelector('.assistant-dock-cursor')).toBeTruthy()
})

test('agent 完成后展示知识提议卡', async () => {
  const agentRun = liveRun({
    steps: [], streamingText: '', final: {
      type: 'final', answer: '已完成', mode: 'agent', model_version: null,
      sources: [], suggestions: [{ type: 'knowledge_proposal', id: 'p1', name: '克拉默法则' }],
    },
  })
  renderShell({ conversation: {
    messages: [], busy: false, error: undefined, agentRun,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(await screen.findByText(/提议新增知识点「克拉默法则」/)).toBeTruthy()
})

test('没有打开 Notebook 时不显示旧 Note 建议卡', () => {
  renderShell()
  expect(screen.queryByText(/提议新增知识点/)).toBeNull()
  expect(screen.queryByRole('button', { name: '写入当前笔记' })).toBeNull()
})

test('agent 回答中的 GFM 表格按表格渲染而不是管道文本', () => {
  renderShell({ conversation: {
    messages: [
      {
        id: 'a9', conversation_id: 'v1', role: 'assistant',
        content: '| 法则 | 用法 |\n| --- | --- |\n| 和差法则 | 逐项求导 |\n| 乘积法则 | 展开后求导 |',
        evidence: [], status: 'completed', created_at: '', mode: 'agent', sources: [],
      },
    ], busy: false, error: undefined, agentRun: null,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(document.querySelector('.assistant-dock-answer table')).toBeTruthy()
  expect(document.querySelectorAll('.assistant-dock-answer th').length).toBe(2)
  expect(document.querySelectorAll('.assistant-dock-answer td').length).toBe(4)
})

test('没有 Notebook 编辑器时不显示旧笔记入口提示或锁定档', () => {
  renderShell()
  const select = screen.getByRole('combobox', { name: '本次提问的作用范围' }) as HTMLSelectElement
  expect(Array.from(select.options).some((option) => option.value === '__note__')).toBe(false)
})
