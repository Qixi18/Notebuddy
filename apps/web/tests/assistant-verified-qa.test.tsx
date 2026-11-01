import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import type { ConversationMessage } from '../src/types'
import { AssistantThread } from '../src/features/assistant/AssistantThread'
import { NotebookScopePanel } from '../src/features/assistant/NotebookScopePanel'

vi.mock('../src/api', () => ({
  api: {
    listNotebookConversations: vi.fn(async () => []),
    createNotebookConversation: vi.fn(async () => ({
      id: 'conv-nb', course_id: null, notebook_id: 'nb1', title: '新对话',
      scope: 'notebook', default_scope: 'notebook',
    })),
    getNotebookDocument: vi.fn(async () => ({ revision: 7, content: { type: 'doc', content: [] } })),
    saveFeedback: vi.fn(async () => ({ id: 'fb1' })),
    listConversationMessages: vi.fn(async () => []),
  },
}))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

function answer(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-1', conversation_id: 'conv-1', role: 'assistant',
    content: '极限描述函数在一点附近的变化趋势。',
    learning_goal: null, status: 'completed', model_version: null, failure_type: null,
    created_at: '2026-11-01T10:00:00Z', evidence: [], mode: 'agent-verified', sources: [],
    ...overrides,
  }
}

function thread(messages: ConversationMessage[], extra: { agentRun?: unknown } = {}) {
  return render(
    <AssistantThread
      ready
      busy={false}
      messages={messages}
      conversationId="conv-1"
      personaName="莉艾尔"
      starters={[]}
      onStarter={() => undefined}
      onFeedback={vi.fn(async () => true)}
      agentRun={extra.agentRun as never}
    />,
  )
}

test('部分未核实的回答显示「部分主张未核实」和口径说明', () => {
  thread([answer({
    verification: {
      status: 'partially_verified',
      notice: '部分事实主张缺少可追溯证据或与来源冲突，已标记为未核实。',
    },
  })])
  expect(screen.getByText('部分主张未核实')).toBeTruthy()
  expect(screen.getByText(/已标记为未核实/)).toBeTruthy()
})

test('已核实的回答显示绿色「已通过证据核验」，且不误报「未核实」', () => {
  thread([answer({ verification: { status: 'verified', notice: null } })])
  expect(screen.getByText('已通过证据核验')).toBeTruthy()
  expect(screen.queryByText('部分主张未核实')).toBeNull()
})

test('没有来源的回答不能显示成已核实', () => {
  thread([answer({
    mode: 'agent-verified',
    verification: { status: 'unverified_no_evidence', notice: '本轮回答没有可引用的课程资料或联网来源。' },
  })])
  expect(screen.getByText('未附来源，未核验')).toBeTruthy()
  expect(screen.queryByText('已通过证据核验')).toBeNull()
})

test('历史消息里的核验状态随消息持久化渲染', () => {
  thread([
    answer({ id: 'old', verification: { status: 'verification_unavailable' } }),
  ])
  expect(screen.getByText('核验不可用，未核验')).toBeTruthy()
})

test('实时块在门禁通过后显示核验状态，正文不再提前出现', () => {
  thread([], {
    agentRun: {
      steps: [],
      streamingText: '已核验的正文',
      thinking: '',
      notice: '已通过证据核验',
      verification: { status: 'verified' },
      final: undefined,
    },
  })
  expect(screen.getAllByText('已通过证据核验').length).toBeGreaterThan(0)
  expect(screen.getByText('已核验的正文')).toBeTruthy()
})

test('Notebook 范围面板用 notebook_id + 已保存 revision 提问，并按核验状态展示', async () => {
  const events = [
    'data: {"type":"status","status":"drafting"}',
    'data: {"type":"status","status":"verified"}',
    'data: {"type":"delta","text":"极限描述函数的变化趋势。"}',
    'data: {"type":"final","answer":"极限描述函数的变化趋势。","mode":"agent-verified",'
      + '"verification":{"status":"verified"},"message_id":"m-final","conversation_title":"极限"}',
  ].join('\n\n') + '\n\n'
  const fetchMock = vi.fn().mockResolvedValue(new Response(events, {
    status: 200, headers: { 'Content-Type': 'text/event-stream' },
  }))
  vi.stubGlobal('fetch', fetchMock)

  const onExit = vi.fn()
  render(<NotebookScopePanel courseId="c1" notebook={{ id: 'nb1', title: '极限笔记' }} onExit={onExit} />)

  await waitFor(() => expect(screen.getByText(/revision 7/)).toBeTruthy())
  /* 流结束后 hook 会按服务端历史回填（真实环境里服务端已持久化这条消息），
     这里把同一份已持久化消息作为接口返回，验证「来源 = 服务端，不靠本地乐观状态」。 */
  vi.mocked(api.listConversationMessages).mockResolvedValue([
    { id: 'u-1', conversation_id: 'conv-nb', role: 'user', content: '什么是极限？',
      learning_goal: null, status: 'completed', model_version: null, failure_type: null,
      created_at: '2026-11-01T10:00:00Z', evidence: [], mode: null, sources: [] },
    answer({
      id: 'm-final', conversation_id: 'conv-nb',
      content: '极限描述函数的变化趋势。',
      verification: { status: 'verified', notice: null },
    }),
  ])
  fireEvent.change(screen.getByPlaceholderText(/问这本/), { target: { value: '什么是极限？' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))

  await waitFor(() => expect(screen.getByText('已通过证据核验')).toBeTruthy())
  expect(screen.getByText('极限描述函数的变化趋势。')).toBeTruthy()

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  expect(url).toContain('/api/v1/conversations/conv-nb/agent-messages')
  const payload = JSON.parse(String(init.body))
  expect(payload.scope).toBe('notebook')
  expect(payload.notebook_context).toMatchObject({
    course_id: 'c1', notebook_id: 'nb1', revision: 7, title: '极限笔记',
  })
  // 只能通过 notebook 会话建立入口，不能退回课程会话
  expect(vi.mocked(api.createNotebookConversation)).toHaveBeenCalledWith('nb1')
  expect(vi.mocked(api.listNotebookConversations)).toHaveBeenCalledWith('nb1')
  expect(onExit).not.toHaveBeenCalled()
})
