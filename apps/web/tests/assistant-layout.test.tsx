import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  api: {
    getWebSearchStatus: vi.fn(async () => ({ configured: true, provider: 'tavily', status: 'ok' })),
    saveFeedback: vi.fn(async () => ({ id: 'fb1' })),
    explainTerm: vi.fn(async () => ({
      original: 'red-black tree', common_translations: ['红黑树'], discipline: '数据结构',
      explanation: '一种自平衡二叉搜索树。', source_note: '课程资料', uncertain: false, sources: [],
    })),
    /* P4：答疑页挂载即按课程拉待确认建议（空列表即可） */
    listCourseSuggestions: vi.fn(async () => []),
    getNote: vi.fn(),
    /* P6：消息全文搜索 */
    searchMessages: vi.fn(async () => []),
    /* P10：自测卷 */
    listQuizzes: vi.fn(async () => []),
    submitAttempts: vi.fn(async () => ({ quiz_id: 'q1', status: 'completed', results: [], score: '0/1' })),
  },
}))

import { api } from '../src/api'
import type { ConversationMessage } from '../src/types'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { AssistantPage } from '../src/pages/AssistantPage'

afterEach(cleanup)

const course = { id: 'c1', name: '数据结构与算法', description: null, created_at: '2026-01-01T00:00:00Z' }
const material = { id: 'm1', course_id: 'c1', lecture_title: '第 3 讲 树与二叉树', topic_title: null, original_filename: 'l3.pptx', media_type: 'pptx', size_bytes: 1, status: 'completed', page_count: 30, created_at: '2026-01-01T00:00:00Z' }
const page = { id: 'p1', material_id: 'm1', page_number: 1, title: '红黑树', raw_text: '', parse_status: 'ok', warning: null, location_type: 'page', location_label: null, stable_location_key: null, extraction_method: 'text', confidence: 1 }

const greeting: ConversationMessage = {
  id: 'local-greeting', conversation_id: 'conv-1', role: 'assistant',
  content: '你好，我是莉艾尔。我会先在当前课程已解析的页面中寻找依据，再陪你一步步把原理梳理清楚。',
  learning_goal: null, status: 'completed', model_version: null, failure_type: null,
  created_at: '', evidence: [], mode: null, sources: [],
}

const answered: ConversationMessage = {
  id: 'msg-1', conversation_id: 'conv-1', role: 'assistant',
  content: '先说结论：插入最多两次旋转就能恢复平衡。[课程资料：第 3 讲 树与二叉树 | 第 18 页]',
  learning_goal: null, status: 'completed', model_version: null, failure_type: null,
  created_at: '2026-10-20T14:02:00Z', evidence: [], mode: 'deepseek-rag',
  sources: [
    { source_type: 'course_material', material_id: 'm1', lecture_title: '第 3 讲 树与二叉树', page_number: 18, snippet: '插入只会破坏性质 4', support_level: 'direct' },
  ],
}

const asked: ConversationMessage = {
  id: 'u1', conversation_id: 'conv-1', role: 'user',
  content: '红黑树插入最多旋转几次？',
  learning_goal: null, status: 'completed', model_version: null, failure_type: null,
  created_at: '2026-10-20T14:01:00Z', evidence: [], mode: null, sources: [],
}

const failed: ConversationMessage = {
  id: 'msg-failed', conversation_id: 'conv-1', role: 'assistant',
  content: '刚才没答上来。',
  learning_goal: null, status: 'failed', model_version: null, failure_type: null,
  created_at: '2026-10-20T14:02:00Z', evidence: [], mode: null, sources: [],
}

function renderPage(overrides: {
  messages?: ConversationMessage[]
  materials?: unknown[]
  conversations?: Array<{ id: string; title: string; updated_at: string; created_at: string; course_id: string; default_scope: string; scope?: string; note_id?: string | null; note_title?: string | null }>
  conversationId?: string
  hasMessages?: boolean
  busy?: boolean
  agentRun?: unknown
  stopAgent?: ReturnType<typeof vi.fn>
  ask?: ReturnType<typeof vi.fn>
  askAgent?: ReturnType<typeof vi.fn>
} = {}) {
  /* 时间戳相对当下生成，分组断言不随运行日期/时区漂移 */
  const hourAgo = new Date(Date.now() - 3600 * 1000).toISOString()
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString()
  const conversation = {
    conversations: overrides.conversations ?? [
      { id: 'conv-1', course_id: 'c1', title: '红黑树的旋转规则', default_scope: 'course', created_at: hourAgo, updated_at: hourAgo },
      { id: 'conv-0', course_id: 'c1', title: '堆排序的时间复杂度', default_scope: 'course', created_at: threeDaysAgo, updated_at: threeDaysAgo },
    ],
    conversationId: 'conversationId' in overrides ? overrides.conversationId : 'conv-1' as string | undefined,
    messages: overrides.messages ?? [greeting],
    hasMessages: overrides.hasMessages ?? false,
    busy: overrides.busy ?? false,
    ready: true,
    error: undefined as string | undefined,
    agentRun: (overrides.agentRun ?? null) as never,
    selectConversation: vi.fn(async () => {}),
    startNewConversation: vi.fn(async () => {}),
    ask: overrides.ask ?? vi.fn(async () => true),
    askAgent: overrides.askAgent ?? vi.fn(async () => true),
    stopAgent: overrides.stopAgent ?? vi.fn(),
  }
  const workspace = {
    courses: [course],
    courseId: 'c1',
    conversationCourseId: 'c1',
    course,
    coursesLoading: false,
    courseContentLoading: false,
    materials: 'materials' in overrides ? overrides.materials : [material],
    selectedMaterialId: undefined,
    setSelectedMaterialId: vi.fn(),
    pages: [page],
    selectedPageNumber: undefined,
    setSelectedPageNumber: vi.fn(),
    openMaterialSource: vi.fn(),
    notes: [],
    upsertNotes: vi.fn(),
    noteDraft: '',
    setNoteDraft: vi.fn(),
    editingNote: false,
    setEditingNote: vi.fn(),
    graph: { nodes: [], edges: [] },
    teacherPersona: 'elf',
    setTeacherPersona: vi.fn(),
    conversation,
    busy: false,
    noteSaving: false,
    noteDirty: false,
    reloadNote: vi.fn(async () => {}),
    error: undefined,
    setError: vi.fn(),
    createCourse: vi.fn(),
    uploadMaterial: vi.fn(),
    retryMaterial: vi.fn(),
    reparseMaterial: vi.fn(),
    requestOCR: vi.fn(),
    saveNote: vi.fn(async () => {}),
    refreshCourses: vi.fn(async () => {}),
    refreshCurrentMaterials: vi.fn(async () => {}),
    refreshCurrentNotes: vi.fn(async () => {}),
  } as never as WorkspaceContextValue

  const renderResult = render(
    <MemoryRouter initialEntries={['/courses/c1/assistant']}>
      <WorkspaceProvider value={workspace}>
        <AssistantPage />
      </WorkspaceProvider>
    </MemoryRouter>,
  )
  return { ...renderResult, conversation }
}

test('三区骨架渲染：左栏课程历史、中栏上下文条与对话、右栏改动栏', () => {
  renderPage()
  expect(screen.getByLabelText('桌宠与会话')).toBeTruthy()
  expect(screen.getByLabelText('课程答疑对话')).toBeTruthy()
  expect(screen.getByLabelText('待确认改动')).toBeTruthy()
  /* 上下文条：可见的「上下文」二字已去掉，靠 aria-label 定位 */
  expect(screen.getByLabelText('提问上下文')).toBeTruthy()
  expect(screen.getByText('数据结构与算法')).toBeTruthy()
  expect(screen.getAllByText('整门课程').length).toBeGreaterThan(0)
  expect(screen.getByText('可以从这里开始')).toBeTruthy()
})

test('欢迎态 starter 点击后填入输入框', () => {
  renderPage()
  fireEvent.click(screen.getByRole('button', { name: /这门课最重要的三个概念是什么/ }))
  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  expect(textarea.value).toBe('这门课最重要的三个概念是什么？')
})

test('Enter 直接发送并走 agent 流式通道；Shift+Enter 只换行', async () => {
  const askAgent = vi.fn(async () => true)
  renderPage({ askAgent, conversationId: undefined, conversations: [] })
  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  fireEvent.change(textarea, { target: { value: '为什么红黑树插入最多两次旋转？' } })
  fireEvent.keyDown(textarea, { key: 'Enter' })
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0][0]).toBe('为什么红黑树插入最多两次旋转？')
  /* 答疑页已切到 agent 通道：范围按 agent 语义下发（全局可查 → scope: 'global'） */
  expect(askAgent.mock.calls[0][1]).toMatchObject({ scope: 'global' })
  expect(askAgent.mock.calls[0][1]).not.toHaveProperty('learningGoal')
})

test('新会话范围默认「全局可查」，首条消息前可改', () => {
  renderPage({ conversationId: undefined, conversations: [], messages: [] })

  /* 未发消息：默认全局可查（左栏脚注与上下文条都显示），且可以点开菜单改范围 */
  expect(screen.getAllByText('全局可查').length).toBeGreaterThan(0)
  fireEvent.click(screen.getAllByTitle('修改提问范围')[0])
  expect(screen.getByRole('menu')).toBeTruthy()
  fireEvent.click(screen.getByRole('menuitemradio', { name: '整门课程' }))
  expect(screen.getAllByText('整门课程').length).toBeGreaterThan(0)
})

test('会话一旦有消息，范围锁定：点击只给提示，菜单不再打开', () => {
  renderPage({ messages: [greeting, { ...greeting, id: 'u1', role: 'user', content: '红黑树是什么？' }], hasMessages: true })

  const trigger = screen.getByTitle('对话已开始回答，范围已锁定；点「＋新对话」可重新选择')
  expect(trigger.className).toContain('is-locked')
  fireEvent.click(trigger)
  expect(screen.getByText(/对话已开始回答，范围已锁定/)).toBeTruthy()
  expect(screen.queryByRole('menuitemradio')).toBeNull()
})

test('切换到的会话按其真实归属展示范围（锁定笔记）', () => {
  const hourAgo = new Date(Date.now() - 3600 * 1000).toISOString()
  renderPage({
    conversationId: 'conv-9',
    conversations: [{ id: 'conv-9', course_id: 'c1', title: '锁定笔记会话', default_scope: 'note', scope: 'note', note_id: 'n1', note_title: '红黑树笔记', created_at: hourAgo, updated_at: hourAgo }],
    messages: [greeting],
  })
  expect(screen.getAllByText('红黑树笔记').length).toBeGreaterThan(0)
})

test('「＋新对话」以全局可查新建，不继承上一段的选择', () => {
  const view = renderPage({ conversationId: undefined, conversations: [], messages: [] })
  fireEvent.click(screen.getAllByRole('button', { name: /＋ 新对话/ })[0])
  expect(view.conversation.startNewConversation).toHaveBeenCalledWith({ scope: 'global' })
})

test('回答正文不露出机器标记，点角标会定位并展开卡底依据', () => {
  renderPage({ messages: [greeting, { ...greeting, id: 'u1', role: 'user', content: '问题' }, answered] })
  expect(screen.queryByText(/课程资料：/)).toBeNull()
  expect(screen.getByLabelText('回答依据')).toBeTruthy()
  /* 初始收起：原文不出现在 DOM 里 */
  expect(document.querySelector('.workspace-source-detail')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: /查看依据 1：第 3 讲 树与二叉树/ }))
  const chip = document.querySelector('.workspace-source-chip.is-active')
  expect(chip).toBeTruthy()
  /* 点角标要直接把原文展开，否则依据在长回答底部、点了像没反应 */
  expect(document.querySelector('.workspace-source-detail')).toBeTruthy()
  expect(screen.getByText('插入只会破坏性质 4')).toBeTruthy()

  /* 展开后仍可手动收起 */
  fireEvent.click(screen.getByRole('button', { name: /收起原文/ }))
  expect(document.querySelector('.workspace-source-detail')).toBeNull()
})

test('课程没有资料时给出上传引导，而不是空屏', () => {
  renderPage({ materials: [] })
  expect(screen.getByText(/这门课还没有可检索的资料/)).toBeTruthy()
  expect(screen.getByRole('link', { name: /去上传课程资料/ })).toBeTruthy()
})

test('点击会话历史切换会话；顶栏搜索按钮打开命令面板并按标题过滤', async () => {
  const { conversation } = renderPage()
  fireEvent.click(screen.getByRole('button', { name: /堆排序的时间复杂度/ }))
  await waitFor(() => expect(conversation.selectConversation).toHaveBeenCalledWith('conv-0'))

  fireEvent.click(screen.getByRole('button', { name: '搜索会话' }))
  const input = screen.getByLabelText('搜索会话标题') as HTMLInputElement
  fireEvent.change(input, { target: { value: '堆排序' } })
  expect(screen.getByRole('dialog', { name: '搜索会话' }).textContent).toContain('堆排序的时间复杂度')
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(screen.queryByRole('dialog', { name: '搜索会话' })).toBeNull()
})

/* ---- P1 中断 ---- */

test('回答进行中：发送键变「停止」，点它就中断这次回答', () => {
  const stopAgent = vi.fn()
  renderPage({ busy: true, stopAgent })
  const stop = screen.getByRole('button', { name: /停止/ })
  fireEvent.click(stop)
  expect(stopAgent).toHaveBeenCalled()
})

test('回答进行中：Esc 也能中断', () => {
  const stopAgent = vi.fn()
  renderPage({ busy: true, stopAgent })
  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  fireEvent.keyDown(textarea, { key: 'Escape' })
  expect(stopAgent).toHaveBeenCalled()
})

test('空闲时没有停止入口，发送键照常可用', () => {
  renderPage()
  expect(screen.queryByRole('button', { name: /停止/ })).toBeNull()
  expect(screen.getByRole('button', { name: /发送/ })).toBeTruthy()
})

test('被中断的实时块标「已中断」，不再显示「执行中」，已收到的正文保留', () => {
  renderPage({
    busy: false,
    agentRun: { steps: [], streamingText: '插入最多两次旋转', aborted: true },
  })
  expect(screen.getByText('已中断')).toBeTruthy()
  expect(screen.queryByText('Agent 执行中')).toBeNull()
  expect(screen.getByText(/插入最多两次旋转/)).toBeTruthy()
})

/* ---- P2 回答卡二次操作 ---- */

test('回答卡可以复制正文，复制后按钮变成「已复制」', async () => {
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  renderPage({ messages: [greeting, asked, answered] })

  fireEvent.click(screen.getByRole('button', { name: '复制' }))
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(answered.content))
  await waitFor(() => expect(screen.getByRole('button', { name: '已复制' })).toBeTruthy())
})

test('失败的回答给出「重试」按钮，重发的是它前面那条原问题', async () => {
  const askAgent = vi.fn(async () => true)
  renderPage({ messages: [greeting, asked, failed], askAgent })

  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0][0]).toBe('红黑树插入最多旋转几次？')
})

test('追问 chips 只把话术填进输入框，不自动发送', () => {
  const askAgent = vi.fn(async () => true)
  renderPage({ messages: [greeting, asked, answered], askAgent })

  fireEvent.click(screen.getByRole('button', { name: '能举个例子吗' }))
  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  expect(textarea.value).toBe('能举个例子吗')
  expect(askAgent).not.toHaveBeenCalled()
})

test('用户气泡显示提问时间', () => {
  renderPage({ messages: [greeting, asked, answered] })
  /* 时间标签跟着运行环境时区走，这里只断言「提问气泡上确实有时间」 */
  expect(document.querySelectorAll('.workspace-msg-user time').length).toBe(1)
})

/* ---- P6 消息全文搜索 ---- */

test('搜索面板消息命中：显示命中片段，点击带定位目标切换会话', async () => {
  vi.mocked(api.searchMessages).mockResolvedValueOnce([
    {
      conversation_id: 'conv-0', conversation_title: '堆排序的时间复杂度',
      message_id: 'msg-hit-1', message_role: 'user',
      snippet: '……复杂度分析里提到的红黑树旋转可以类比……', created_at: '2026-10-20T14:01:00Z',
    },
  ])
  const { conversation } = renderPage()
  fireEvent.click(screen.getByRole('button', { name: '搜索会话' }))
  fireEvent.change(screen.getByLabelText('搜索会话标题'), { target: { value: '旋转' } })

  /* 标题不命中的关键词走消息级搜索：高亮关键词 + 显示会话名（标题命中的会话组照常显示） */
  await waitFor(() => {
    const mark = document.querySelector('.workspace-palette-snippet mark')
    expect(mark?.textContent).toBe('旋转')
  })
  const groups = document.querySelectorAll('.workspace-palette-group')
  expect([...groups].map((node) => node.textContent)).toEqual(['会话', '消息'])
  expect(document.querySelector('.workspace-palette-hit-title')?.textContent).toBe('堆排序的时间复杂度')

  fireEvent.click(document.querySelector('.workspace-palette-snippet')?.closest('button') as Element)
  expect(conversation.selectConversation).toHaveBeenCalledWith('conv-0', 'msg-hit-1')
})

/* ---- P3 课件收窄 ---- */
/* 「整门课程」是两步：先选档（展开课程子菜单），再点当前课程落档 */
function pickCourseScope() {
  fireEvent.click(screen.getAllByTitle('修改提问范围')[0])
  fireEvent.click(screen.getByRole('menuitemradio', { name: '整门课程' }))
  const coursePick = document.querySelector('.workspace-scope-pick')
  if (!coursePick) throw new Error('课程子菜单未展开')
  fireEvent.click(coursePick)
}

function pickGlobalScope() {
  fireEvent.click(screen.getAllByTitle('修改提问范围')[0])
  fireEvent.click(screen.getByRole('menuitemradio', { name: '全局可查' }))
}

test('课件收窄控件仅在「整门课程」档显示，点开列出当前课程课件', () => {
  renderPage()
  /* 默认全局可查：没有收窄入口 */
  expect(screen.queryByRole('button', { name: /课件 · / })).toBeNull()

  pickCourseScope()
  const chip = screen.getByRole('button', { name: /课件 · / })
  expect(chip.textContent).toContain('全部')
  fireEvent.click(chip)
  const menu = screen.getByRole('menu', { name: '选择收窄课件' })
  expect(menu.textContent).toContain('全部课件')
  expect(menu.textContent).toContain('第 3 讲 树与二叉树')
})

test('选中课件后 payload 带消息级 material_id，范围仍是 course；切回全局档即复位', async () => {
  const askAgent = vi.fn(async () => true)
  renderPage({ askAgent, conversationId: undefined, conversations: [] })

  pickCourseScope()
  fireEvent.click(screen.getByRole('button', { name: /课件 · / }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: '第 3 讲 树与二叉树' }))
  /* 选中态：chip 标题切到该讲并高亮 */
  expect(screen.getByRole('button', { name: /课件 · 第 3 讲 树与二叉树/ }).className).toContain('is-active')

  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  fireEvent.change(textarea, { target: { value: '这一讲的核心是什么？' } })
  fireEvent.keyDown(textarea, { key: 'Enter' })
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0][1]).toMatchObject({ scope: 'course', materialId: 'm1' })

  /* 切回全局档：收窄复位，payload 不再带 materialId */
  pickGlobalScope()
  expect(screen.queryByRole('button', { name: /课件 · / })).toBeNull()
  fireEvent.change(textarea, { target: { value: '全局问题' } })
  fireEvent.keyDown(textarea, { key: 'Enter' })
  await waitFor(() => expect(askAgent).toHaveBeenCalledTimes(2))
  expect(askAgent.mock.calls[1][1]).toMatchObject({ scope: 'global' })
  expect(askAgent.mock.calls[1][1]).not.toHaveProperty('materialId')
})

test('没有已完成课件时不显示收窄控件', () => {
  renderPage({ materials: [{ ...material, status: 'processing' }] })
  pickCourseScope()
  expect(screen.queryByRole('button', { name: /课件 · / })).toBeNull()
})


/* ---- P9 学习模式 + P10 自测卷 ---- */

test('学习模式 chip 点击切换并随请求下发', async () => {
  const askAgent = vi.fn(async () => true)
  renderPage({ askAgent, conversationId: undefined, conversations: [] })
  const chip = screen.getByRole('button', { name: '直接答' })
  fireEvent.click(chip)
  expect(screen.getByRole('button', { name: '引导我' }).getAttribute('aria-pressed')).toBe('true')

  const textarea = screen.getByLabelText('课程问题') as HTMLTextAreaElement
  fireEvent.change(textarea, { target: { value: '这个概念我搞不懂' } })
  fireEvent.keyDown(textarea, { key: 'Enter' })
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0][1]).toMatchObject({ learningMode: 'guided' })
})

test('自测卷：拉题、作答、交卷判分', async () => {
  vi.mocked(api.listQuizzes).mockResolvedValueOnce([
    {
      id: 'q1', title: '行列式小测', status: 'active',
      items: [{ id: 'qi1', seq: 1, type: 'choice', stem: '行列式为零说明？', options: ['可逆', '不可逆'] }],
    },
  ])
  vi.mocked(api.submitAttempts).mockResolvedValueOnce({
    quiz_id: 'q1', status: 'completed',
    results: [{ item_id: 'qi1', seq: 1, correct: false, answer: '不可逆', explanation: '行列式为零等价于不可逆。', comment: '' }],
    score: '0/1',
  })
  renderPage({
    agentRun: {
      steps: [], streamingText: '',
      final: {
        type: 'final', answer: '我出了一道题，请在卡片上作答。', mode: 'agent', model_version: 'test',
        suggestions: [{ type: 'quiz', id: 's1', quiz_id: 'q1', title: '行列式小测', item_count: 1 }],
      },
    } as never,
  })

  await waitFor(() => expect(screen.getByText(/行列式为零说明/)).toBeTruthy())
  fireEvent.click(screen.getByRole('radio', { name: /不可逆/ }))
  fireEvent.click(screen.getByRole('button', { name: '交卷' }))
  await waitFor(() => expect(screen.getByText(/✗ 答错了/)).toBeTruthy())
  expect(screen.getByText(/得分 0\/1/)).toBeTruthy()
  expect(screen.getByText(/参考答案：不可逆/)).toBeTruthy()
})
