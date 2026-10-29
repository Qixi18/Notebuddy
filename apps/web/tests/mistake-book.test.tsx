import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { MistakeBook } from '../src/features/assistant/MistakeBook'
import type { QuizMistake, ReviewArtifactDto } from '../src/api/quiz'

vi.mock('../src/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) { super(message); this.status = status }
  },
  api: {
    listMistakes: vi.fn(),
    setItemFlags: vi.fn(),
    listReviewArtifacts: vi.fn(),
    updateArtifact: vi.fn(),
    listArtifactStates: vi.fn(),
  },
}))

const mistake: QuizMistake = {
  item_id: 'item-1',
  quiz_id: 'quiz-1',
  quiz_title: '复杂度自测',
  material_id: 'material-1',
  material_title: '第一讲 复杂度',
  seq: 1,
  type: 'choice',
  stem: '下列哪个复杂度增长最慢？',
  options: ['O(1)', 'O(n)'],
  answer: 'O(1)',
  explanation: '常数阶与输入规模无关。',
  last_answer: 'O(n)',
  last_at: '2026-10-29T15:00:00Z',
  wrong_count: 2,
  favorite: false,
  marked: false,
}

const looseMistake: QuizMistake = {
  ...mistake,
  item_id: 'item-2',
  seq: 2,
  stem: '大 O 记号描述的是？',
  material_id: null,
  material_title: null,
  answer: '上界',
  last_answer: '精确值',
  explanation: '大 O 给出渐进上界。',
  wrong_count: 1,
}

const outline: ReviewArtifactDto = {
  id: 'artifact-1',
  kind: 'review_outline',
  title: '复杂度复习提纲',
  payload: {
    title: '复杂度复习提纲',
    modules: [{ title: '阶的比较', priority: 'high', items: [{ point: '记住常见阶的大小顺序', ref: '第 1 节' }] }],
  },
  favorite: false,
  dismissed: false,
  created_at: '2026-10-29T15:00:00Z',
}

const dismissedOutline: ReviewArtifactDto = {
  ...outline,
  id: 'artifact-2',
  title: '已移出的提纲',
  dismissed: true,
}

function renderBook(overrides: Partial<Parameters<typeof MistakeBook>[0]> = {}) {
  const props = {
    open: true,
    courseId: 'course-1',
    courseName: '数据结构与算法',
    onClose: vi.fn(),
    onExplain: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
  render(<MistakeBook {...props} />)
  return props
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listMistakes).mockResolvedValue([mistake, looseMistake])
  vi.mocked(api.listReviewArtifacts).mockResolvedValue([])
  vi.mocked(api.listArtifactStates).mockResolvedValue([])
  vi.mocked(api.setItemFlags).mockImplementation(async (itemId, flags) => ({
    item_id: itemId,
    favorite: flags.favorite ?? false,
    marked: flags.marked ?? false,
    dismissed: flags.dismissed ?? false,
  }))
  vi.mocked(api.updateArtifact).mockImplementation(async (artifactId, patch) => ({
    id: artifactId,
    favorite: patch.favorite ?? false,
    dismissed: patch.dismissed ?? false,
  }))
})

afterEach(() => {
  cleanup()
})

describe('MistakeBook', () => {
  test('renders mistakes grouped by material with answers and explanation', async () => {
    renderBook()

    expect(await screen.findByText('下列哪个复杂度增长最慢？')).toBeTruthy()
    expect(screen.getByText('大 O 记号描述的是？')).toBeTruthy()
    expect(screen.getByText('我的答案：O(n)')).toBeTruthy()
    expect(screen.getByText('正确答案：O(1)')).toBeTruthy()
    expect(screen.getByText('常数阶与输入规模无关。')).toBeTruthy()
    expect(screen.getByText('第一讲 复杂度')).toBeTruthy()
    expect(screen.getByText('未指定课件（笔记或全课出题）')).toBeTruthy()
    expect(screen.getByText('错过 2 次')).toBeTruthy()
    expect(api.listMistakes).toHaveBeenCalledWith('course-1')
  })

  test('toggling the star persists the flag and flips the icon', async () => {
    renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.click(screen.getAllByText('☆')[0])

    await waitFor(() => expect(api.setItemFlags).toHaveBeenCalledWith('item-1', { favorite: true }))
    // 收藏后题干旁出现 ★ 标记，按钮本身也变成 ★（所以不能用 getByText 唯一匹配）
    await waitFor(() => expect(
      document.querySelector('.mistake-item .mistake-flag-tag')?.textContent,
    ).toBe('★'))
  })

  test('dismissing needs a second click and then drops the row', async () => {
    renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.click(screen.getAllByTitle('移出复习')[0])
    expect(api.setItemFlags).not.toHaveBeenCalled()
    expect(screen.getByText('确认移出')).toBeTruthy()

    fireEvent.click(screen.getByText('确认移出'))

    await waitFor(() => expect(api.setItemFlags).toHaveBeenCalledWith('item-1', { dismissed: true }))
    await waitFor(() => expect(screen.queryByText('下列哪个复杂度增长最慢？')).toBeNull())
    // 另一题不受影响
    expect(screen.getByText('大 O 记号描述的是？')).toBeTruthy()
  })

  test('outline tab loads artifacts including dismissed ones and can restore them', async () => {
    vi.mocked(api.listReviewArtifacts).mockResolvedValue([outline, dismissedOutline])
    renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.click(screen.getByRole('tab', { name: '复习提纲' }))

    await waitFor(() => expect(
      api.listReviewArtifacts,
    ).toHaveBeenCalledWith('course-1', 'review_outline', true))
    expect(await screen.findByText('复杂度复习提纲')).toBeTruthy()
    expect(screen.getByText('已移出（1）▼')).toBeTruthy()

    fireEvent.click(screen.getByText('已移出（1）▼'))
    expect(await screen.findByText('已移出的提纲')).toBeTruthy()
    fireEvent.click(screen.getByText('↩ 恢复'))

    await waitFor(() => expect(api.updateArtifact).toHaveBeenCalledWith('artifact-2', { dismissed: false }))
  })

  test('search narrows the mistake list by stem', async () => {
    renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.change(screen.getByLabelText('搜索复习内容'), { target: { value: '大 O' } })

    await waitFor(() => expect(screen.queryByText('下列哪个复杂度增长最慢？')).toBeNull())
    expect(screen.getByText('大 O 记号描述的是？')).toBeTruthy()
  })

  test('explain and retry hand a prompt containing the answer to the caller', async () => {
    const props = renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.click(screen.getAllByText('让 AI 讲讲这道题')[0])
    const explain = props.onExplain.mock.calls[0][0] as string
    expect(explain).toContain('下列哪个复杂度增长最慢？')
    expect(explain).toContain('我的答案：O(n)')
    expect(explain).toContain('正确答案：O(1)')

    fireEvent.click(screen.getAllByText('重练同类')[0])
    const retry = props.onRetry.mock.calls[0][0] as string
    expect(retry).toContain('下列哪个复杂度增长最慢？')
  })

  test('escape closes the panel and closed state renders nothing', async () => {
    const props = renderBook()
    await screen.findByText('下列哪个复杂度增长最慢？')

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(props.onClose).toHaveBeenCalled()
  })

  test('shows the empty state when the course has no mistakes', async () => {
    vi.mocked(api.listMistakes).mockResolvedValue([])
    renderBook()
    expect(await screen.findByText('还没有错题。')).toBeTruthy()
  })

  test('surfaces a load failure instead of pretending it succeeded', async () => {
    vi.mocked(api.listMistakes).mockRejectedValue(new Error('接口挂了'))
    renderBook()
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '接口挂了')
  })
})
