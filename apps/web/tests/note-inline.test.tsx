import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { NoteSuggestionsInline } from '../src/features/assistant/NoteSuggestionsInline'

afterEach(cleanup)

const suggestion = { id: 's1', proposed_markdown: '# 标题\n新正文', impact: '精简正文', status: 'pending' }
// JSX 字符串属性不处理转义，换行必须走变量
const content = '# 标题\n旧正文'

test('原位渲染红删绿增，全部采纳提交建议全文', () => {
  const onReview = vi.fn()
  render(<NoteSuggestionsInline content={content} suggestions={[suggestion]} onReview={onReview} />)

  expect(screen.getByText(/精简正文/)).toBeTruthy()
  expect(document.querySelector('.agent-diff-removed')?.textContent).toBe('旧正文')
  expect(document.querySelector('.agent-diff-added')?.textContent).toBe('新正文')

  fireEvent.click(screen.getByRole('button', { name: '采纳进原文' }))
  expect(onReview).toHaveBeenCalledWith(suggestion, 'confirm', '# 标题\n新正文')
})

test('取消勾选变更块后按部分采纳提交', () => {
  const onReview = vi.fn()
  render(<NoteSuggestionsInline content={content} suggestions={[suggestion]} onReview={onReview} />)

  fireEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: /采纳所选项（0\/1 块）/ })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /采纳所选项/ }))
  expect(onReview).toHaveBeenCalledWith(suggestion, 'confirm', content)
})

test('多条建议提示依次展示', () => {
  const onReview = vi.fn()
  render(
    <NoteSuggestionsInline
      content="A"
      suggestions={[suggestion, { ...suggestion, id: 's2', proposed_markdown: 'B' }]}
      onReview={onReview}
    />,
  )

  expect(screen.getByText(/共 2 条，正在展示第 1 条/)).toBeTruthy()
  // 只渲染第一条的 diff：content "A" 与建议无公共行 → 1 删 2 增
  expect(document.querySelectorAll('.agent-diff-removed').length).toBe(1)
  expect(document.querySelectorAll('.agent-diff-added').length).toBe(2)
})
