import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { AssistantThread } from '../src/features/assistant/AssistantThread'
import type { ConversationMessage } from '../src/types'

afterEach(cleanup)

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

function renderThread() {
  const onFeedback = vi.fn(async () => true)
  render(
    <AssistantThread
      ready
      busy={false}
      messages={[answer]}
      conversationId="c1"
      personaName="沃雅妮莎"
      starters={[]}
      onStarter={() => {}}
      onFeedback={onFeedback}
    />,
  )
  return onFeedback
}

test('点「需改进」只展开原因，不直接提交', () => {
  const onFeedback = renderThread()

  fireEvent.click(screen.getByRole('button', { name: '需改进' }))

  expect(onFeedback).not.toHaveBeenCalled()
  expect(screen.getByRole('group', { name: '选择不理想的原因' })).toBeTruthy()
  /* 五个原因都要在，缺一个就等于少一档反馈口径 */
  for (const reason of ['答非所问', '引用不准', '太啰嗦', '有错误', '其他']) {
    expect(screen.getByRole('button', { name: reason })).toBeTruthy()
  }
})

test('选中的原因作为 comment 一并提交，并按 not_helpful 落库', async () => {
  const onFeedback = renderThread()

  fireEvent.click(screen.getByRole('button', { name: '需改进' }))
  fireEvent.click(screen.getByRole('button', { name: '引用不准' }))

  await waitFor(() => {
    expect(onFeedback).toHaveBeenCalledWith('m1', 'not_helpful', '引用不准')
  })
  await waitFor(() => expect(screen.getByText('反馈已保存')).toBeTruthy())
})

test('「有帮助」不带 comment，保持原有行为', async () => {
  const onFeedback = renderThread()

  fireEvent.click(screen.getByRole('button', { name: '有帮助' }))

  await waitFor(() => expect(onFeedback).toHaveBeenCalledWith('m1', 'helpful', undefined))
})

test('再点一次「需改进」收起原因选项', () => {
  renderThread()
  const toggle = screen.getByRole('button', { name: '需改进' })

  fireEvent.click(toggle)
  fireEvent.click(toggle)

  expect(screen.queryByRole('group', { name: '选择不理想的原因' })).toBeNull()
})
