import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { WorkspaceProvider } from '../src/components/AppLayout'
import { AssistantDock } from '../src/features/assistant/AssistantDock'
import { NotebookBridgeProvider, useRegisterNotebookBridge, type NotebookBridgeValue } from '../src/features/notebook-editor/NotebookBridge'

vi.mock('../src/api', () => ({
  api: { listNotebookEditSuggestions: vi.fn(async () => []) },
}))

const askAgent = vi.fn(async () => true)
const notebook: NotebookBridgeValue = {
  courseId: 'c1', notebookId: 'book-1', title: '真实编辑上下文', revision: 3, editVersion: 1,
  excerpt: '已保存的笔记正文', selection: null,
  isDirty: () => false, adoptDocument: () => true, insertAI: () => true,
}

function NotebookEditorContext() {
  useRegisterNotebookBridge(notebook)
  return null
}

function Harness({ locked = false }: { locked?: boolean }) {
  return <MemoryRouter><WorkspaceProvider value={{
    courseId: 'c1', conversationCourseId: 'c1', courses: [{ id: 'c1', name: '逻辑电路' }],
    materials: [], teacherPersona: 'elf', openMaterialSource: () => {},
    conversation: {
      messages: [], conversations: [{ id: 'a', scope: 'course' }], conversationId: 'a',
      hasMessages: locked, busy: false, askAgent,
    },
  } as never}><NotebookBridgeProvider>
    <NotebookEditorContext />
    <AssistantDock width={360} onWidthChange={() => {}} onClose={() => {}} onResizeStateChange={() => {}} />
  </NotebookBridgeProvider></WorkspaceProvider></MemoryRouter>
}

beforeEach(() => { askAgent.mockClear() })
afterEach(cleanup)

test('真实 Notebook 上下文首轮显式选择全局后按 global 发送', async () => {
  render(<Harness />)
  expect(await screen.findByText(/正在编辑整篇笔记/)).toBeTruthy()
  fireEvent.change(screen.getByLabelText('本次提问的作用范围'), { target: { value: '__global__' } })
  fireEvent.change(screen.getByLabelText('快速提问'), { target: { value: '其他课程有哪些相关内容？' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0]?.[1]).toMatchObject({ scope: 'global', notebookContext: { notebook_id: 'book-1' } })
})

test('锁定 course 会话优先于之前未发送的 global 选择', async () => {
  const view = render(<Harness />)
  fireEvent.change(screen.getByLabelText('本次提问的作用范围'), { target: { value: '__global__' } })
  view.rerender(<Harness locked />)
  expect((screen.getByLabelText('本次提问的作用范围') as HTMLSelectElement).value).toBe('')
  fireEvent.change(screen.getByLabelText('快速提问'), { target: { value: '继续问题' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(askAgent).toHaveBeenCalled())
  expect(askAgent.mock.calls[0]?.[1].scope).toBe('course')
})
