import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { memo, useEffect, useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { WorkspaceProvider } from '../src/components/AppLayout'
import { AssistantDock } from '../src/features/assistant/AssistantDock'
import { AssistantPage } from '../src/pages/AssistantPage'
import { NotebookBridgeProvider, useNotebookBridge, useRegisterNotebookBridge, type NotebookBridgeValue } from '../src/features/notebook-editor/NotebookBridge'

vi.mock('../src/api', () => ({
  api: {
    listNotebookEditSuggestions: vi.fn(async () => []),
    getWebSearchStatus: vi.fn(async () => ({ configured: false, provider: 'none', status: 'ok' })),
    listNotebooks: vi.fn(async () => []),
    listNotebookConversations: vi.fn(async () => []),
    createNotebookConversation: vi.fn(async () => ({
      id: 'conv-nb', course_id: null, notebook_id: 'nb1', title: '新对话',
      scope: 'notebook', default_scope: 'notebook',
    })),
    getNotebookDocument: vi.fn(async () => ({ revision: 7, content: { type: 'doc', content: [] } })),
  },
}))

const askAgent = vi.fn(async () => true)
const bridgeProbeRender = vi.fn()
const notebook: NotebookBridgeValue = {
  courseId: 'c1', notebookId: 'book-1', title: '真实编辑上下文', revision: 3, editVersion: 1,
  excerpt: '已保存的笔记正文', selection: null,
  isDirty: () => false, adoptDocument: () => true, insertAI: () => true,
}

function NotebookEditorContext() {
  useRegisterNotebookBridge(notebook)
  return null
}

const BridgeProbe = memo(function BridgeProbe() {
  useNotebookBridge()
  bridgeProbeRender()
  return null
})

function BridgeRerenderHarness() {
  const [revision, setRevision] = useState(0)
  return <>
    <button type="button" onClick={() => setRevision((value) => value + 1)}>重渲染 {revision}</button>
    <NotebookBridgeProvider>
      <NotebookEditorContext />
      <BridgeProbe />
    </NotebookBridgeProvider>
  </>
}

function Harness({ locked = false }: { locked?: boolean }) {
  return <MemoryRouter><WorkspaceProvider value={{
    courseId: 'c1', conversationCourseId: 'c1', courses: [{ id: 'c1', name: '逻辑电路' }],
    materials: [], teacherPersona: 'elf', openMaterialSource: () => {},
    conversation: {
      messages: [], conversations: [{ id: 'a', scope: 'notebook', notebook_id: 'book-1' }], conversationId: 'a',
      hasMessages: locked, busy: false, askAgent,
    },
  } as never}><NotebookBridgeProvider>
    <NotebookEditorContext />
    <AssistantDock width={360} onWidthChange={() => {}} onClose={() => {}} onResizeStateChange={() => {}} />
  </NotebookBridgeProvider></WorkspaceProvider></MemoryRouter>
}

beforeEach(() => { askAgent.mockClear(); bridgeProbeRender.mockClear() })
afterEach(cleanup)

test('Notebook Bridge context stays stable on unrelated parent renders', async () => {
  render(<BridgeRerenderHarness />)
  await waitFor(() => expect(bridgeProbeRender).toHaveBeenCalledTimes(2))
  const rendersAfterRegistration = bridgeProbeRender.mock.calls.length

  fireEvent.click(screen.getByRole('button', { name: '重渲染 0' }))

  expect(screen.getByRole('button', { name: '重渲染 1' })).toBeTruthy()
  expect(bridgeProbeRender).toHaveBeenCalledTimes(rendersAfterRegistration)
})

test('真实 Notebook 上下文固定使用 Notebook 范围，答疑不修改正文', async () => {
  render(<Harness />)
  expect(await screen.findByText(/正在查看整篇 Notebook/)).toBeTruthy()
  expect(screen.queryByLabelText('本次提问的作用范围')).toBeNull()
  fireEvent.change(screen.getByLabelText('快速提问'), { target: { value: '这份笔记的核心内容是什么？' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0]?.[1]).toMatchObject({
    scope: 'notebook', notebookContext: { course_id: 'c1', notebook_id: 'book-1', revision: 3 },
  })
  expect(screen.queryByRole('button', { name: '插入到选区后' })).toBeNull()
})

test('Notebook 会话不暴露课程或全局范围切换', () => {
  render(<Harness locked />)
  expect(screen.queryByLabelText('本次提问的作用范围')).toBeNull()
  expect(screen.getByText('作用范围：当前 Notebook')).toBeTruthy()
})

test('Notebook 页悬浮坞提供「在完整答疑页打开」，课程场景入口文案不变', () => {
  render(<Harness />)
  const jump = screen.getByText('在完整答疑页打开')
  expect(jump.getAttribute('href')).toBe('/courses/c1/assistant')
  expect(screen.queryByText('打开完整答疑')).toBeNull()
})

test('答疑页消费悬浮坞跳转 state，直接进入该 Notebook 范围面板', async () => {
  /* AssistantPage 的桌宠宽视口 hook 依赖 matchMedia，jsdom 没有 */
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })))
  /* 模拟真实时序：课程会话列表异步到达（conversationId 从无到有），
     验证范围 chip 对齐 effect 不会把跳转 state 进入的 Notebook 范围冲掉 */
  function JumpHarness() {
    const [conversationId, setConversationId] = useState<string | undefined>(undefined)
    const [conversations, setConversations] = useState<Array<{ id: string; scope: string }>>([])
    useEffect(() => {
      const timer = setTimeout(() => {
        setConversations([{ id: 'conv-c1', scope: 'course' }])
        setConversationId('conv-c1')
      }, 40)
      return () => clearTimeout(timer)
    }, [])
    return (
      <MemoryRouter initialEntries={[{
        pathname: '/courses/c1/assistant',
        state: { notebookScope: { id: 'nb1', title: '极限笔记' } },
      }]}>
        <WorkspaceProvider value={{
          courseId: 'c1', conversationCourseId: 'c1', courses: [{ id: 'c1', name: '逻辑电路' }],
          materials: [], openMaterialSource: () => {},
          conversation: {
            messages: [], conversations, conversationId, ready: true,
            busy: false, hasMessages: false, agentRun: null, error: undefined,
            askAgent, stopAgent: vi.fn(), renameConversation: vi.fn(), deleteConversation: vi.fn(),
            startNewConversation: vi.fn(async () => undefined),
            agentSuggestionsByMessage: {}, pendingMessageId: undefined, consumePendingMessage: () => {},
          },
        } as never}>
          <AssistantPage />
        </WorkspaceProvider>
      </MemoryRouter>
    )
  }
  render(<JumpHarness />)
  /* NotebookScopePanel 读取已保存正文 revision 后渲染，说明跳转 state 已被消费 */
  await waitFor(() => expect(screen.getByText(/revision 7/)).toBeTruthy())
  /* 会话列表异步到达、conversationId 变化后，Notebook 面板仍然在（不被对齐 effect 冲掉） */
  await new Promise((resolve) => setTimeout(resolve, 120))
  expect(screen.getByText(/revision 7/)).toBeTruthy()
})
