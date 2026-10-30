import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

const searchMessages = vi.fn()
vi.mock('../src/api', () => ({
  api: { searchMessages: (...args: unknown[]) => searchMessages(...args) },
}))

import { AssistantThread } from '../src/features/assistant/AssistantThread'
import { ConversationSearch } from '../src/features/assistant/ConversationList'
import type { Conversation, ConversationMessage } from '../src/types'

afterEach(() => {
  cleanup()
  searchMessages.mockReset()
})

const conversation: Conversation = {
  id: 'c1',
  course_id: 'course-1',
  title: '行列式讨论',
  default_scope: 'course',
  created_at: '2026-10-30T00:00:00Z',
  updated_at: '2026-10-30T00:00:00Z',
}

const hit = {
  message_id: 'm9',
  conversation_id: 'c1',
  conversation_title: '行列式讨论',
  message_role: 'assistant',
  snippet: '行列式按行展开可以得到降阶公式',
}

function renderSearch() {
  const onSelect = vi.fn()
  const onSelectMessage = vi.fn()
  const onClose = vi.fn()
  render(
    <ConversationSearch
      conversations={[conversation]}
      courseId="course-1"
      onSelect={onSelect}
      onSelectMessage={onSelectMessage}
      onClose={onClose}
    />,
  )
  return { onSelect, onSelectMessage, onClose }
}

test('消息命中点进去时带上 messageId，而不是只开会话', async () => {
  searchMessages.mockResolvedValue([hit])
  const { onSelectMessage } = renderSearch()

  fireEvent.change(screen.getByRole('textbox'), { target: { value: '行列式' } })

  const mark = await screen.findByText('行列式', { selector: 'mark' })
  fireEvent.click(mark.closest('button')!)

  expect(onSelectMessage).toHaveBeenCalledWith('c1', 'm9')
})

test('命中片段里的关键词被 mark 包住，其余文字保持原样', async () => {
  searchMessages.mockResolvedValue([hit])
  renderSearch()

  fireEvent.change(screen.getByRole('textbox'), { target: { value: '行列式' } })

  const mark = await screen.findByText('行列式', { selector: 'mark' })
  expect(mark.textContent).toBe('行列式')
  /* 整段片段仍要完整渲染，只是命中部分套了 mark */
  expect(screen.getByText(/按行展开可以得到降阶公式/)).toBeTruthy()
})

const answer: ConversationMessage = {
  id: 'm1',
  conversation_id: 'c1',
  role: 'assistant',
  content: '这是回答正文。',
  status: 'completed',
  created_at: '2026-10-30T00:00:00Z',
  evidence: [],
  mode: null,
  sources: [],
}

test('定位目标出现在历史后滚动到该条并消费掉信号', async () => {
  const scrollIntoView = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoView
  const onHighlightConsumed = vi.fn()

  render(
    <AssistantThread
      ready
      busy={false}
      messages={[answer]}
      conversationId="c1"
      personaName="沃雅妮莎"
      starters={[]}
      onStarter={() => {}}
      onFeedback={async () => true}
      highlightMessageId="m1"
      onHighlightConsumed={onHighlightConsumed}
    />,
  )

  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(onHighlightConsumed).toHaveBeenCalled())
})

test('目标消息不在当前历史里时不动也不消费', async () => {
  const scrollIntoView = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoView
  const onHighlightConsumed = vi.fn()

  render(
    <AssistantThread
      ready
      busy={false}
      messages={[answer]}
      conversationId="c1"
      personaName="沃雅妮莎"
      starters={[]}
      onStarter={() => {}}
      onFeedback={async () => true}
      highlightMessageId="m-not-here"
      onHighlightConsumed={onHighlightConsumed}
    />,
  )

  await new Promise((resolve) => setTimeout(resolve, 150))
  expect(scrollIntoView).not.toHaveBeenCalled()
  expect(onHighlightConsumed).not.toHaveBeenCalled()
})
