import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

/**
 * v6 P1 回归：会话切换/停止时流的生命周期。
 * useConversation 是三条提问入口的唯一状态源，这里直接驱动 hook 验证
 * abort、agentRun 清理与 busy 归还，页面级测试（mock 整个 conversation）覆盖不到这些。
 */

const streamState = vi.hoisted(() => ({
  captured: {} as {
    signal?: AbortSignal
    handlers?: Record<string, (event: unknown) => void>
    settle?: (value?: unknown) => void
  },
}))

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error { status = 0 },
  api: {
    listConversations: vi.fn(async () => [
      { id: 'conv-a', course_id: 'c1', title: '会话A', default_scope: 'global', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]),
    createConversation: vi.fn(async (_courseId: string, title: string) => ({
      id: 'conv-b', course_id: 'c1', title, default_scope: 'global', created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
    })),
    listConversationMessages: vi.fn(async () => []),
  },
}))

vi.mock('../src/api/agent', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/agent')>()
  return {
    ...actual,
    // 模拟一条长流：记录 handlers/signal，收到 abort 才以 AbortError 结束；
    // settle() 供用例主动正常收尾（模拟 final 后流结束）
    streamAgentMessage: vi.fn((_cid: string, _payload: unknown, handlers: Record<string, (event: unknown) => void>, signal?: AbortSignal) => {
      streamState.captured.handlers = handlers
      streamState.captured.signal = signal
      return new Promise((resolve, reject) => {
        streamState.captured.settle = resolve
        signal?.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')))
      })
    }),
  }
})

import { useConversation } from '../src/features/conversation/useConversation'

afterEach(cleanup)

const state: { conv: ReturnType<typeof useConversation> | null } = { conv: null }

function Harness() {
  state.conv = useConversation('c1')
  return null
}

async function renderReady() {
  render(<Harness />)
  await waitFor(() => expect(state.conv?.ready).toBe(true))
  /* 断言一律走 getConv()：state.conv 每次 re-render 都会被 Harness 刷新 */
  return () => state.conv!
}

test('流式中切换会话：旧流被中止、agentRun 清空、busy 正常归还', async () => {
  const getConv = await renderReady()

  let askSettled = false
  await act(async () => {
    void getConv().askAgent('旧会话的问题', { scope: 'global' }).then(() => { askSettled = true })
  })
  expect(getConv().busy).toBe(true)
  expect(getConv().agentRun).not.toBeNull()

  await act(async () => { await getConv().selectConversation('conv-b') })

  expect(streamState.captured.signal?.aborted).toBe(true)
  expect(getConv().conversationId).toBe('conv-b')
  expect(getConv().agentRun).toBeNull()
  await waitFor(() => expect(getConv().busy).toBe(false))
  expect(askSettled).toBe(true)

  /* 旧流的迟到事件不得写入新状态（守门 + agentRun 已清空） */
  await act(async () => {
    streamState.captured.handlers?.onDelta?.({ type: 'delta', text: '旧流迟到内容' })
    streamState.captured.handlers?.onStep?.({ type: 'step', tool: 'search_course', detail: 'x', status: 'running' })
  })
  expect(getConv().agentRun).toBeNull()
})

test('用户点停止（同会话内中断）：aborted 标记生效、busy 复位', async () => {
  const getConv = await renderReady()

  await act(async () => {
    void getConv().askAgent('问题', { scope: 'global' })
  })
  expect(getConv().busy).toBe(true)

  await act(async () => { getConv().stopAgent() })

  await waitFor(() => expect(getConv().busy).toBe(false))
  expect(getConv().agentRun?.aborted).toBe(true)
})

test('停止后再开新对话：agentRun 残留被清理、正常建会话', async () => {
  const getConv = await renderReady()

  await act(async () => {
    void getConv().askAgent('问题', { scope: 'global' })
  })
  await act(async () => { getConv().stopAgent() })
  await waitFor(() => expect(getConv().busy).toBe(false))
  expect(getConv().agentRun?.aborted).toBe(true)

  await act(async () => { await getConv().startNewConversation({ scope: 'global' }) })
  expect(getConv().agentRun).toBeNull()
  expect(getConv().pendingMessageId).toBeUndefined()
  expect(getConv().conversationId).toBe('conv-b')
})

test('流式期间 startNewConversation 被单飞守门拦截（UI 同时禁用新对话按钮）', async () => {
  const getConv = await renderReady()

  await act(async () => {
    void getConv().askAgent('问题', { scope: 'global' })
  })
  await act(async () => { await getConv().startNewConversation({ scope: 'global' }) })

  /* 守门生效：未建新会话、未打断流 */
  expect(getConv().conversationId).toBe('conv-a')
  expect(streamState.captured.signal?.aborted).toBe(false)
  expect(getConv().busy).toBe(true)
})

test('同会话继续提问：上一轮技能建议保留，不随 agentRun 重置消失', async () => {
  const getConv = await renderReady()

  await act(async () => { void getConv().askAgent('第一问', { scope: 'global' }) })
  await act(async () => {
    streamState.captured.handlers?.onFinal?.({
      type: 'final', answer: '第一轮回答', mode: 'agent', model_version: null,
      sources: [], message_id: 'msg-1',
      suggestions: [{ type: 'quiz', id: 'quiz-1', quiz_id: 'quiz-1', title: '行列式小测', item_count: 2 }],
    })
    streamState.captured.settle?.()
  })
  await waitFor(() => expect(getConv().busy).toBe(false))
  expect(getConv().agentSuggestionsByMessage['msg-1']).toHaveLength(1)

  /* 第二问重置 agentRun，但会话级建议必须原样保留（v6 用户反馈 bug 的回归用例） */
  await act(async () => { void getConv().askAgent('第二问', { scope: 'global' }) })
  expect(getConv().agentRun).not.toBeNull()
  expect(getConv().agentRun?.final).toBeUndefined()
  expect(getConv().agentSuggestionsByMessage['msg-1']).toHaveLength(1)

  await act(async () => {
    streamState.captured.handlers?.onFinal?.({
      type: 'final', answer: '第二轮回答', mode: 'agent', model_version: null,
      sources: [], message_id: 'msg-2',
      suggestions: [{ type: 'review_outline', id: 'o-1', title: '提纲', module_count: 1, item_count: 1, modules: [] }],
    })
    streamState.captured.settle?.()
  })
  await waitFor(() => expect(getConv().busy).toBe(false))
  /* 各轮建议按消息分桶、互不覆盖 */
  expect(getConv().agentSuggestionsByMessage['msg-1']).toHaveLength(1)
  expect(getConv().agentSuggestionsByMessage['msg-2']).toHaveLength(1)
})
