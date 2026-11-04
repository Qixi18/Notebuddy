import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

vi.mock('../src/components/SettingsPanel', () => ({ SettingsPanel: () => null }))
vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  api: {
    listMaterials: vi.fn(async () => []),
    updateNote: vi.fn(async () => ({ title: '行列式笔记' })),
    listSuggestions: vi.fn(async () => []),
    reviewSuggestion: vi.fn(async () => ({ title: '行列式笔记' })),
    /* P4 多目标：建议涉及的目标笔记按 note_id 取正文 */
    getNote: vi.fn(async () => ({ id: 'n1', title: '行列式笔记', content_markdown: '# 行列式\n已有正文。', revision_number: 1 })),
    listCourseSuggestions: vi.fn(async () => []),
  },
}))

import { api } from '../src/api'
import { AppLayout, WorkspaceProvider } from '../src/components/AppLayout'
import { DOCK_STORAGE } from '../src/features/assistant/dockLayout'
import type { AgentRunState } from '../src/features/conversation/useConversation'

afterEach(cleanup)
beforeEach(() => {
  localStorage.clear()
  vi.mocked(api.listSuggestions).mockClear()
  vi.mocked(api.reviewSuggestion).mockClear()
  vi.mocked(api.listSuggestions).mockResolvedValue([])
})

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

async function renderShell(overrides: Record<string, unknown> = {}) {
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
    conversation: {
      messages: [], busy: false, error: undefined, agentRun: null,
      ask: async () => true, askAgent, startNewConversation: async () => {},
    },
    error: undefined,
    setError: () => {},
    ...overrides,
  } as never
  const router = createMemoryRouter(
    [{ path: '*', element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider> }],
    { initialEntries: ['/courses/c1/notebook'] },
  )
  render(<RouterProvider router={router} />)
  await screen.findByRole('complementary', { name: '课程学习助手' }, { timeout: 5000 })
}

function scopeSelect() {
  return screen.getByLabelText(/本次提问的作用范围/) as HTMLSelectElement
}

test('旧 Note 路径不再提供锁定入口，也不发送 reading_context.note_id', async () => {
  await renderShell()
  const select = scopeSelect()
  const options = Array.from(select.options).map((option) => option.value)
  expect(options).not.toContain('__note__')
  expect(options).toContain('__global__')

  fireEvent.change(screen.getByLabelText(/快速提问/), { target: { value: '帮我整理这一节' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0]?.[0]).toBe('帮我整理这一节')
  expect(askAgent.mock.calls[0]?.[1].scope).toBe('course')
  expect(askAgent.mock.calls[0]?.[1].readingContext).toBeUndefined()
})

test('全局档不带笔记节选，scope 传 global', async () => {
  await renderShell()
  fireEvent.change(scopeSelect(), { target: { value: '__global__' } })
  fireEvent.change(screen.getByLabelText(/快速提问/), { target: { value: '别的课程里有相关内容吗' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  const options = askAgent.mock.calls[0]?.[1]
  expect(options.scope).toBe('global')
  expect(options.readingContext?.excerpt).toBeUndefined()
})

test('agent 执行中显示步骤时间线与流式文本', async () => {
  const agentRun = liveRun({
    steps: [
      { type: 'step', tool: 'search_course', detail: '检索「行列式」', status: 'running' },
      { type: 'step', tool: 'search_course', detail: '命中 2 条课件片段', status: 'done' },
    ],
    streamingText: '行列式是线性代数的基本工具',
  })
  await renderShell({ conversation: {
    messages: [], busy: true, error: undefined, agentRun,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(screen.getByText(/检索课程资料/)).toBeTruthy()
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
  await renderShell({ conversation: {
    messages: [], busy: false, error: undefined, agentRun,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(await screen.findByText(/提议新增知识点「克拉默法则」/)).toBeTruthy()
})

test('AI Dock 隐藏旧 Note 修改建议和回写入口', async () => {
  await renderShell({ conversation: {
    messages: [], busy: false, error: undefined, agentRun: null,
    ask: async () => true, askAgent, startNewConversation: async () => {},
  } })

  expect(screen.queryByRole('button', { name: '写入当前笔记' })).toBeNull()
  expect(screen.queryByText(/整理正文/)).toBeNull()
  expect(api.listSuggestions).not.toHaveBeenCalled()
})

test('agent 回答中的 GFM 表格按表格渲染而不是管道文本', async () => {
  await renderShell({ conversation: {
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

test('普通页面不再提示进入旧 Note 编辑流程，也没有锁定 Note 范围', async () => {
  await renderShell({ selectedNote: undefined })

  expect(screen.queryByText(/点开一个具体小节/)).toBeNull()
  const select = screen.getByRole('combobox', { name: '本次提问的作用范围' }) as HTMLSelectElement
  expect(Array.from(select.options).some((option) => option.value === '__note__')).toBe(false)
})
