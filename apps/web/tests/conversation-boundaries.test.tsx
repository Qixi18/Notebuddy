import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { streamAgentMessage } from '../src/api/agent'
import { api } from '../src/api'
import { useConversation } from '../src/features/conversation/useConversation'

vi.mock('../src/api', () => ({
  api: {
    listConversations: vi.fn(),
    createConversation: vi.fn(),
    listConversationMessages: vi.fn(),
  },
}))

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function responseFor(events: string): Response {
  return new Response(events, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

test('an error or truncated agent stream cannot be reported as success', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(responseFor('data: {"type":"error","message":"模型失败"}\n\n'))
    .mockResolvedValueOnce(responseFor('data: {"type":"delta","text":"一半"}\n\n'))
    .mockResolvedValueOnce(responseFor('data: {"type":"final","answer":"完整","mode":"agent"}\n\n')))
  try {
    await expect(streamAgentMessage('c', { question: '问题', scope: 'course' }, {})).rejects.toThrow('模型失败')
    await expect(streamAgentMessage('c', { question: '问题', scope: 'course' }, {})).rejects.toThrow('未收到最终回答')
    await expect(streamAgentMessage('c', { question: '问题', scope: 'course' }, {})).resolves.toMatchObject({ answer: '完整' })
  } finally {
    vi.unstubAllGlobals()
  }
})

test('older conversation history cannot overwrite a newer selection', async () => {
  let resolveOld!: (messages: never[]) => void
  vi.mocked(api.listConversations).mockResolvedValue([
    { id: 'a' }, { id: 'b' }, { id: 'c' },
  ] as never)
  vi.mocked(api.listConversationMessages).mockImplementation((id) => {
    if (id === 'a') return Promise.resolve([])
    if (id === 'b') return new Promise((resolve) => { resolveOld = resolve as typeof resolveOld })
    return Promise.resolve([{ id: 'c-message', role: 'assistant', content: '新会话内容' }] as never)
  })
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  let oldRequest!: Promise<void>
  act(() => { oldRequest = result.current.selectConversation('b') })
  await act(async () => { await result.current.selectConversation('c') })
  await act(async () => { resolveOld([{ id: 'b-message', role: 'assistant', content: '旧会话内容' }] as never); await oldRequest })
  expect(result.current.conversationId).toBe('c')
  expect(result.current.messages[0]?.id).toBe('c-message')
})

test('failed agent stream reloads the saved failure and clears the live answer', async () => {
  vi.mocked(api.listConversations).mockResolvedValue([{ id: 'a' }] as never)
  vi.mocked(api.listConversationMessages)
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([
      { id: 'user', role: 'user', content: '问题' },
      { id: 'failed', role: 'assistant', status: 'failed', content: '本次回答未完成' },
    ] as never)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    responseFor('data: {"type":"delta","text":"部分回答"}\n\ndata: {"type":"error","message":"模型失败"}\n\n'),
  ))
  try {
    const { result } = renderHook(() => useConversation('course-1'))
    await waitFor(() => expect(result.current.ready).toBe(true))
    let sent = true
    await act(async () => { sent = await result.current.askAgent('问题', { scope: 'course' }) })
    expect(sent).toBe(false)
    expect(result.current.error).toBe('模型失败')
    expect(result.current.agentRun).toBeNull()
    expect(result.current.messages.map((message) => message.id)).toEqual(['user', 'failed'])
  } finally {
    vi.unstubAllGlobals()
  }
})
