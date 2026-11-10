import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { NotebookEditSuggestionCards } from '../src/features/assistant/AgentCards'
import type { NotebookEditSuggestion } from '../src/types'

afterEach(cleanup)

const suggestion: NotebookEditSuggestion = {
  id: 'sug-1',
  notebook_id: 'book-1',
  notebook_title: '高等数学笔记',
  base_revision: 3,
  rationale: '补充易错点',
  operations: [
    { op: 'insert_after_heading', anchor: '第一章 极限', content: '易错点：左右极限不相等时极限不存在。' },
    { op: 'append', content: '补充：极限的四则运算法则。' },
  ],
  proposed_content: null,
  status: 'pending',
  created_at: '2026-11-06T00:00:00Z',
  reviewed_at: null,
}

describe('NotebookEditSuggestionCards（ADR-0005 编辑建议卡）', () => {
  it('渲染建议的操作清单，默认全部勾选', () => {
    render(
      <NotebookEditSuggestionCards
        suggestions={[suggestion]}
        onReview={vi.fn()}
      />,
    )
    expect(screen.getByText(/补充易错点/)).toBeTruthy()
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    expect(boxes).toHaveLength(2)
    expect(boxes.every((box) => box.checked)).toBe(true)
    expect(screen.getByText('采纳所选操作（2/2）')).toBeTruthy()
  })

  it('取消勾选后按所选操作序号提交采纳', () => {
    const onReview = vi.fn()
    render(
      <NotebookEditSuggestionCards
        suggestions={[suggestion]}
        onReview={onReview}
      />,
    )
    fireEvent.click(screen.getAllByRole('checkbox')[0])
    fireEvent.click(screen.getByText('采纳所选操作（1/2）'))
    expect(onReview).toHaveBeenCalledWith(suggestion, 'accept', [1])
  })

  it('忽略按钮以 reject 决定回调', () => {
    const onReview = vi.fn()
    render(
      <NotebookEditSuggestionCards
        suggestions={[suggestion]}
        onReview={onReview}
      />,
    )
    fireEvent.click(screen.getByText('忽略'))
    expect(onReview).toHaveBeenCalledWith(suggestion, 'reject')
  })

  it('busy 时按钮禁用，notice 显示在卡片区', () => {
    render(
      <NotebookEditSuggestionCards
        suggestions={[suggestion]}
        busyId="sug-1"
        notice="当前笔记有未保存修改。请先保存正文，再确认这条建议。"
        onReview={vi.fn()}
      />,
    )
    const confirm = screen.getByText('写入中…') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    expect(screen.getByText(/请先保存正文/)).toBeTruthy()
  })

  it('无建议时不渲染', () => {
    const { container } = render(
      <NotebookEditSuggestionCards suggestions={[]} onReview={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
