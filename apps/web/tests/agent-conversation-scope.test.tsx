import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { api } from '../src/api'
import { useConversation } from '../src/features/conversation/useConversation'
import type { Conversation } from '../src/types'

vi.mock('../src/api', () => ({
  api: {
    listConversations: vi.fn(), createConversation: vi.fn(), listConversationMessages: vi.fn(),
    sendConversationMessage: vi.fn(),
  },
}))

const emptyConversation = {
  id: 'a', course_id: 'course-1', title: '新对话', scope: 'global', default_scope: 'global',
  note_id: null, note_title: null,
} as Conversation

function response(events = 'data: {"type":"final","answer":"完整回答","mode":"agent"}\n\n') {
  return new Response(events, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.listConversations).mockResolvedValue([emptyConversation])
  vi.mocked(api.listConversationMessages).mockResolvedValue([])
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test.each(['course', 'note'] as const)('首轮 final 即使没有标题也同步 %s 范围及笔记快照', async (scope) => {
  vi.mocked(api.listConversations).mockResolvedValueOnce([emptyConversation]).mockRejectedValue(new Error('offline'))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response()))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.askAgent('问题', { scope, notebookContext: {
      course_id: 'course-1', notebook_id: 'book-1', revision: 3, title: '整篇笔记',
    } })
  })
  expect(result.current.conversations[0]).toMatchObject({
    scope, default_scope: scope, note_id: scope === 'note' ? 'book-1' : null,
    note_title: scope === 'note' ? '整篇笔记' : null,
  })
})

test('流式失败后读取服务器已锁定的权威范围与笔记元数据', async () => {
  const saved = { ...emptyConversation, scope: 'note', default_scope: 'note', note_id: 'book-1', note_title: '服务端笔记标题' } as Conversation
  vi.mocked(api.listConversations).mockResolvedValueOnce([emptyConversation]).mockResolvedValue([saved])
  vi.mocked(api.listConversationMessages).mockResolvedValueOnce([]).mockResolvedValue([
    { id: 'user', role: 'user', content: '问题' },
  ] as never)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response('data: {"type":"error","message":"模型失败"}\n\n')))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => { expect(await result.current.askAgent('问题', { scope: 'note' })).toBe(false) })
  expect(result.current.conversations[0]).toMatchObject(saved)
  expect(result.current.hasMessages).toBe(true)
  expect(result.current.error).toBe('模型失败')
})

test('思考文本跨工具及正文事件累计，同时同步首问范围', async () => {
  vi.mocked(api.listConversations).mockResolvedValueOnce([emptyConversation]).mockRejectedValue(new Error('offline'))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response([
    'data: {"type":"thinking","text":"先阅读。"}\n\n',
    'data: {"type":"step","tool":"search_course","detail":"检索完成","status":"done"}\n\n',
    'data: {"type":"thinking","text":"再比较。"}\n\n',
    'data: {"type":"delta","text":"回答正文"}\n\n',
    'data: {"type":"final","answer":"回答正文","mode":"agent"}\n\n',
  ].join(''))))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => { await result.current.askAgent('问题', { scope: 'course' }) })
  expect(result.current.agentRun).toMatchObject({ thinking: '先阅读。再比较。', streamingText: '回答正文' })
  expect(result.current.conversations[0]).toMatchObject({ scope: 'course', default_scope: 'course' })
})

test('中断保留流式正文并刷新服务器已锁定的范围', async () => {
  const saved = { ...emptyConversation, scope: 'course', default_scope: 'course' } as Conversation
  vi.mocked(api.listConversations).mockResolvedValueOnce([emptyConversation]).mockResolvedValue([saved])
  vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => Promise.resolve(new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"type":"delta","text":"保留的部分回答"}\n\n'))
      init.signal?.addEventListener('abort', () => controller.error(new DOMException('stopped', 'AbortError')))
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } }))))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  let sent!: Promise<boolean>
  act(() => { sent = result.current.askAgent('问题', { scope: 'course' }) })
  await waitFor(() => expect(result.current.agentRun?.streamingText).toBe('保留的部分回答'))
  await act(async () => { result.current.stopAgent(); await sent })
  expect(result.current.conversations[0].scope).toBe('course')
  expect(result.current.agentRun).toMatchObject({ aborted: true, streamingText: '保留的部分回答' })
  expect(result.current.error).toBeUndefined()
})

test('后端拒绝首问时权威空历史保持未锁定并允许改范围', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '笔记已更新' }), {
    status: 409, headers: { 'Content-Type': 'application/json' },
  })))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => { expect(await result.current.askAgent('问题', { scope: 'course' })).toBe(false) })
  expect(result.current.conversations[0].scope).toBe('global')
  expect(result.current.hasMessages).toBe(false)
})

test('已有会话不因本轮 options 改变归属，收尾以服务器快照为准', async () => {
  const saved = { ...emptyConversation, scope: 'note', default_scope: 'note', note_id: 'book-1', note_title: '原笔记' } as Conversation
  vi.mocked(api.listConversations).mockResolvedValue([saved])
  vi.mocked(api.listConversationMessages).mockResolvedValue([{ id: 'old-user', role: 'user', content: '旧问题' }] as never)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response('data: {"type":"final","answer":"完整回答","mode":"agent","conversation_title":"已命名"}\n\n')))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => { await result.current.askAgent('另一问', { scope: 'global' }) })
  expect(result.current.conversations[0]).toMatchObject({ scope: 'note', note_id: 'book-1', note_title: '原笔记' })
})

test('普通问答后续轮次也不能按本轮参数迁移已锁定归属', async () => {
  const saved = { ...emptyConversation, scope: 'note', default_scope: 'note', note_id: 'book-1', note_title: '原笔记' } as Conversation
  vi.mocked(api.listConversations).mockResolvedValue([saved])
  vi.mocked(api.listConversationMessages).mockResolvedValue([{ id: 'old-user', role: 'user', content: '旧问题' }] as never)
  vi.mocked(api.sendConversationMessage).mockResolvedValue({
    id: 'answer', role: 'assistant', content: '回答', conversation_title: '已经命名',
  } as never)
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => { await result.current.ask('另一问', { kind: 'global' }) })
  expect(result.current.conversations[0]).toMatchObject({ scope: 'note', note_id: 'book-1', note_title: '原笔记' })
})

test('旧请求迟到的权威刷新不能覆盖新选择及其会话元数据', async () => {
  const other = { ...emptyConversation, id: 'b', scope: 'course', default_scope: 'course', title: '另一会话' } as Conversation
  let resolveRefresh!: (items: Conversation[]) => void
  vi.mocked(api.listConversations)
    .mockResolvedValueOnce([emptyConversation, other])
    .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
  vi.mocked(api.listConversationMessages).mockImplementation((id) => Promise.resolve(id === 'b'
    ? [{ id: 'b-user', role: 'user', content: '另一会话的问题' }] as never : []))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response('data: {"type":"final","answer":"回答","mode":"agent","conversation_title":"本轮标题"}\n\n')))
  const { result } = renderHook(() => useConversation('course-1'))
  await waitFor(() => expect(result.current.ready).toBe(true))
  let sent!: Promise<boolean>
  act(() => { sent = result.current.askAgent('问题', { scope: 'course' }) })
  await waitFor(() => expect(api.listConversations).toHaveBeenCalledTimes(2))
  await act(async () => { await result.current.selectConversation('b', 'b-user') })
  await act(async () => {
    resolveRefresh([{ ...emptyConversation, title: '旧元数据' }, { ...other, scope: 'global' }])
    await sent
  })
  expect(result.current.conversationId).toBe('b')
  expect(result.current.messages[0].id).toBe('b-user')
  expect(result.current.conversations.find((item) => item.id === 'b')?.scope).toBe('course')
  expect(result.current.conversations.find((item) => item.id === 'a')?.title).toBe('本轮标题')
  expect(result.current.pendingMessageId).toBe('b-user')
  act(() => result.current.consumePendingMessage())
  expect(result.current.pendingMessageId).toBeUndefined()
})
