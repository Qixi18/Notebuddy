import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { QuizMistake } from '../src/api/quiz'

const { listMistakes } = vi.hoisted(() => ({ listMistakes: vi.fn() }))

vi.mock('../src/api', () => ({ api: { listMistakes } }))

import { MistakeBook } from '../src/features/assistant/MistakeBook'

afterEach(() => cleanup())

const mistakes: QuizMistake[] = [
  {
    item_id: 'i1', quiz_id: 'q1', quiz_title: '需求层次小测',
    material_id: 'm1', material_title: '第 1 讲',
    seq: 2, type: 'choice', stem: '并发 500 的响应指标属于哪层需求？',
    options: ['业务需求', '系统需求'], answer: '系统需求',
    explanation: '材料第 3 页：系统需求含性能等非功能需求。',
    last_answer: '业务需求', last_at: '2026-10-25T14:26:21', wrong_count: 2,
  },
  {
    item_id: 'i2', quiz_id: 'q2', quiz_title: '矩阵运算小测',
    material_id: 'm2', material_title: '第 2 讲',
    seq: 1, type: 'short', stem: '写出矩阵加法的定义。',
    options: [], answer: '对应元素相加，仍为 m×n 矩阵',
    explanation: '要点：对应元素相加。',
    last_answer: '各个', last_at: '2026-10-24T17:10:13', wrong_count: 1,
  },
]

describe('MistakeBook', () => {
  beforeEach(() => {
    listMistakes.mockReset()
    listMistakes.mockResolvedValue(mistakes)
  })

  test('按课件分组展示错题，标出历史错次', async () => {
    render(<MistakeBook open courseId="c1" courseName="软件" onClose={() => {}} onExplain={() => {}} onRetry={() => {}} />)
    await waitFor(() => expect(screen.getByText('第 1 讲')).toBeTruthy())
    expect(screen.getByText('第 2 讲')).toBeTruthy()
    expect(screen.getByText('错过 2 次')).toBeTruthy()
    expect(screen.getByText(/我的答案：业务需求/)).toBeTruthy()
    expect(screen.getByText(/正确答案：系统需求/)).toBeTruthy()
  })

  test('空错题本给出「考考我」引导', async () => {
    listMistakes.mockResolvedValue([])
    render(<MistakeBook open courseId="c1" onClose={() => {}} onExplain={() => {}} onRetry={() => {}} />)
    await waitFor(() => expect(screen.getByText('还没有错题。')).toBeTruthy())
  })

  test('两个动作分别注入讲解与重练提示，且携带题目上下文', async () => {
    const onExplain = vi.fn()
    const onRetry = vi.fn()
    render(<MistakeBook open courseId="c1" onClose={() => {}} onExplain={onExplain} onRetry={onRetry} />)
    await waitFor(() => expect(screen.getAllByText('让 AI 讲讲这道题').length).toBe(2))

    fireEvent.click(screen.getAllByText('让 AI 讲讲这道题')[0])
    const explainPrompt = onExplain.mock.calls[0][0] as string
    expect(explainPrompt).toContain('诊断我的错因')
    expect(explainPrompt).toContain('业务需求')
    expect(explainPrompt).toContain('系统需求')

    fireEvent.click(screen.getAllByText('重练同类')[0])
    expect(onRetry.mock.calls[0][0]).toContain('再出两道题')
  })
})
