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
      messages: [], conversations: [{ id: 'a', scope: 'notebook', notebook_id: 'book-1' }], conversationId: 'a',
      hasMessages: locked, busy: false, askAgent,
    },
  } as never}><NotebookBridgeProvider>
    <NotebookEditorContext />
    <AssistantDock width={360} onWidthChange={() => {}} onClose={() => {}} onResizeStateChange={() => {}} />
  </NotebookBridgeProvider></WorkspaceProvider></MemoryRouter>
}

beforeEach(() => { askAgent.mockClear() })
afterEach(cleanup)

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
