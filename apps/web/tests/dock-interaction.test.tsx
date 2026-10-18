import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

vi.mock('../src/SettingsPanel', () => ({ SettingsPanel: () => null }))
/* 悬浮坞在非课程页会自己拉一份资料列表；测试里不打真实请求。
   agent 化后还会读建议列表（不做真实请求），提交走 askAgent 流式通道 */
vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  api: {
    listMaterials: vi.fn(async () => []),
    updateNote: vi.fn(async () => ({ title: '依赖注入笔记' })),
    listSuggestions: vi.fn(async () => []),
    reviewSuggestion: vi.fn(async () => ({ title: '依赖注入笔记' })),
  },
}))

import { AppLayout, WorkspaceProvider } from '../src/components/AppLayout'
import { DOCK_STORAGE, DOCK_WIDTH_DEFAULT } from '../src/features/assistant/dockLayout'

afterEach(cleanup)
beforeEach(() => localStorage.clear())

const course = { id: 'c1', name: '软件工程', created_at: '2026-01-01T00:00:00Z' }
const note = {
  id: 'n1', course_id: 'c1', title: '依赖注入笔记', content_markdown: '已有正文。',
  material_id: null, section_key: null, section_order: 0, knowledge_node_id: '',
  content_origin: 'user', user_locked: false, revision_number: 3,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}
const idleConversation = {
  messages: [], busy: false, error: undefined, agentRun: null,
  ask: async () => true, askAgent: async () => true, startNewConversation: async () => {},
}
/** 一轮已完成的问答：一条提问 + 一条带来源的回答，用于验证来源清单与回写 */
const answeredConversation = {
  ...idleConversation,
  messages: [
    { id: 'u1', conversation_id: 'v1', role: 'user', content: '什么是依赖注入？', evidence: [], status: 'completed', created_at: '' },
    {
      id: 'a1', conversation_id: 'v1', role: 'assistant', content: '依赖注入是一种……', evidence: [],
      status: 'completed', created_at: '', mode: 'deepseek-rag',
      sources: [
        { source_type: 'course_material', material_id: 'm1', lecture_title: '第 3 讲 · 设计模式', page_number: 3, snippet: '依赖注入指……' },
        { source_type: 'web', url: 'https://example.com/di', site_name: 'Example', title: '依赖注入概览', snippet: '网络补充说明' },
      ],
    },
  ],
}
const workspace = {
  courseId: 'c1',
  course,
  courses: [course],
  conversationCourseId: 'c1',
  materials: [],
  selectedNote: undefined,
  noteDirty: false,
  noteSaving: false,
  openMaterialSource: () => {},
  refreshCurrentNotes: async () => {},
  teacherPersona: 'elf',
  conversation: idleConversation,
  error: undefined,
  setError: () => {},
  setEditingNote: () => {},
} as never

function renderShell(initialEntry: string, overrides: Record<string, unknown> = {}) {
  const value = { ...(workspace as Record<string, unknown>), ...overrides }
  const router = createMemoryRouter(
    [{ path: '*', element: <WorkspaceProvider value={value as never}><AppLayout /></WorkspaceProvider> }],
    { initialEntries: [initialEntry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

function shell() {
  return document.querySelector('.app-shell') as HTMLElement
}

/** jsdom 不做布局，clientWidth 恒为 0；上限按外壳宽度算，所以给它一个真实值 */
function stubShellWidth(width: number) {
  Object.defineProperty(shell(), 'clientWidth', { configurable: true, value: width })
}

function dockWidthVar() {
  return shell().style.getPropertyValue('--dock-w')
}

function grip() {
  return screen.getByRole('separator', { name: /拖拽调整答疑坞宽度/ })
}

test('抽屉收起时，右下角悬浮球是唯一入口；点开后悬浮球让位给抽屉', () => {
  renderShell('/courses/c1/notebook')
  const fab = screen.getByRole('button', { name: '打开课程学习助手' })
  expect(document.querySelector('.assistant-dock')).toBeNull()

  fireEvent.click(fab)
  expect(document.querySelector('.assistant-dock')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '打开课程学习助手' })).toBeNull()
  expect(localStorage.getItem(DOCK_STORAGE.open)).toBe('true')
})

test('抽屉里的收起按钮把入口还给悬浮球，并记住收起状态', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  expect(document.querySelector('.assistant-dock')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '收起答疑坞' }))
  expect(document.querySelector('.assistant-dock')).toBeNull()
  expect(screen.getByRole('button', { name: '打开课程学习助手' })).toBeTruthy()
  expect(localStorage.getItem(DOCK_STORAGE.open)).toBe('false')
})

test('悬浮球全局常驻：首页、知识森林、课程页、回收站都能唤起抽屉', () => {
  for (const pathname of ['/', '/forest', '/courses/c1/notebook', '/recycle']) {
    localStorage.clear() // 每轮都从「收起」起步，否则上一轮的展开状态会让悬浮球不再渲染
    renderShell(pathname)
    fireEvent.click(screen.getByRole('button', { name: '打开课程学习助手' }))
    expect(document.querySelector('.assistant-dock'), pathname).toBeTruthy()
    expect(localStorage.getItem(DOCK_STORAGE.open), pathname).toBe('true')
    cleanup()
  }
})

test('答疑页整页不提供悬浮球与抽屉（那一页本身就是完整助手）', () => {
  renderShell('/courses/c1/assistant')
  expect(screen.queryByRole('button', { name: '打开课程学习助手' })).toBeNull()
  expect(document.querySelector('.assistant-dock')).toBeNull()
  cleanup()

  // 已记录为展开态时也不能在该页弹出抽屉
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/assistant')
  expect(document.querySelector('.assistant-dock')).toBeNull()
})

test('非课程页（首页）打开的悬浮坞照样能提问，并说明课程落点', () => {
  localStorage.clear()
  renderShell('/', { courseId: undefined, course: undefined })
  fireEvent.click(screen.getByRole('button', { name: '打开课程学习助手' }))

  expect(screen.getByRole('textbox', { name: '快速提问' })).toBeTruthy()
  const context = document.querySelector('.assistant-dock-context')
  expect(context?.textContent).toContain('软件工程')
  // 回落要讲清原因，而不是让用户以为自己在某门课里
  expect(context?.textContent).toContain('最近访问')
})

test('快捷提示只把提示词填进输入框，不直接发送', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  const input = screen.getByRole('textbox', { name: '快速提问' }) as HTMLTextAreaElement
  expect(input.value).toBe('')

  fireEvent.click(screen.getByRole('button', { name: '解释概念' }))
  expect(input.value).toContain('解释')
})

test('回答后展示来源清单与回答模式，检索结果显性化', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook', { conversation: answeredConversation })

  expect(screen.getByText('回答依据 · 2 条')).toBeTruthy()
  const sources = document.querySelector('.assistant-dock-sources')
  expect(sources?.textContent).toContain('第 3 讲 · 设计模式')
  expect(sources?.textContent).toContain('依赖注入概览')
  expect(document.querySelector('.assistant-dock-mode')?.textContent).toContain('依据课程课件')
})

test('作用范围可收窄到某份课件，并随提问一起带给后端', async () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  const askAgent = vi.fn(async () => true)
  renderShell('/courses/c1/notebook', {
    conversation: { ...idleConversation, askAgent },
    materials: [{ id: 'm1', course_id: 'c1', lecture_title: '第 3 讲 · 设计模式' }],
  })

  fireEvent.change(screen.getByRole('combobox', { name: '本次提问的作用范围' }), { target: { value: 'm1' } })
  expect(document.querySelector('.assistant-dock-context')?.textContent).toContain('第 3 讲 · 设计模式')

  fireEvent.change(screen.getByRole('textbox', { name: '快速提问' }), { target: { value: '这个概念怎么理解' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(askAgent).toHaveBeenCalledWith('这个概念怎么理解', {
    scope: 'course', materialId: 'm1', readingContext: undefined,
  }))
})

test('写入当前笔记只在「正打开着笔记且没有未保存改动」时可用', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  // 资料页没有打开笔记 → 禁用
  renderShell('/courses/c1/materials', { conversation: answeredConversation, selectedNote: note })
  expect((screen.getByRole('button', { name: '写入当前笔记' }) as HTMLButtonElement).disabled).toBe(true)
  cleanup()

  // 笔记本页 + 选中的笔记 + 无未保存改动 → 可用
  renderShell('/courses/c1/notebook', { conversation: answeredConversation, selectedNote: note })
  expect((screen.getByRole('button', { name: '写入当前笔记' }) as HTMLButtonElement).disabled).toBe(false)
  cleanup()

  // 同一页但笔记有未保存改动 → 拒绝回写，避免把用户的字冲掉
  renderShell('/courses/c1/notebook', { conversation: answeredConversation, selectedNote: note, noteDirty: true })
  expect((screen.getByRole('button', { name: '写入当前笔记' }) as HTMLButtonElement).disabled).toBe(true)
})

test('拖分界条实时改宽：往左拖变宽，宽度写进 CSS 变量并落进 localStorage', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  stubShellWidth(1400)

  fireEvent.pointerDown(grip(), { clientX: 300, pointerId: 1 })
  expect(shell().className).toContain('app-shell-dock-resizing')
  fireEvent.pointerMove(window, { clientX: 180 })
  expect(dockWidthVar()).toBe('460px')
  fireEvent.pointerUp(window)

  expect(shell().className).not.toContain('app-shell-dock-resizing')
  expect(localStorage.getItem(DOCK_STORAGE.width)).toBe('460')
})

test('宽度上限是外壳总宽的 72%，拖过头只停在边界', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  stubShellWidth(1000)

  fireEvent.pointerDown(grip(), { clientX: 300, pointerId: 1 })
  fireEvent.pointerMove(window, { clientX: -2000 })
  expect(dockWidthVar()).toBe('720px')
  fireEvent.pointerUp(window)
})

test('拖得太窄松手视为「我要关掉」：抽屉收合，宽度记回默认值', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  stubShellWidth(1400)

  fireEvent.pointerDown(grip(), { clientX: 300, pointerId: 1 })
  fireEvent.pointerMove(window, { clientX: 820 })
  fireEvent.pointerUp(window)

  expect(document.querySelector('.assistant-dock')).toBeNull()
  expect(screen.getByRole('button', { name: '打开课程学习助手' })).toBeTruthy()
  expect(localStorage.getItem(DOCK_STORAGE.width)).toBe(String(DOCK_WIDTH_DEFAULT))
})

test('双击分界条复位到默认宽度', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  localStorage.setItem(DOCK_STORAGE.width, '520')
  renderShell('/courses/c1/notebook')
  stubShellWidth(1400)
  expect(dockWidthVar()).toBe('520px')

  fireEvent.doubleClick(grip())
  expect(dockWidthVar()).toBe(`${DOCK_WIDTH_DEFAULT}px`)
})

test('方向键可以微调宽度，外壳宽度变量随之更新', () => {
  localStorage.setItem(DOCK_STORAGE.open, 'true')
  renderShell('/courses/c1/notebook')
  stubShellWidth(1400)

  fireEvent.keyDown(grip(), { key: 'ArrowLeft' })
  expect(dockWidthVar()).toBe('364px')
  fireEvent.keyDown(grip(), { key: 'ArrowRight' })
  expect(dockWidthVar()).toBe('340px')
})
