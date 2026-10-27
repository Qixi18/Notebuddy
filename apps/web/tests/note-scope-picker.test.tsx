import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { NoteScopePicker } from '../src/features/assistant/NoteScopePicker'
import type { Course, NotebookSummary } from '../src/types'

afterEach(cleanup)

const courses: Course[] = [
  { id: 'c1', name: '软件', description: null, created_at: '' },
  { id: 'c2', name: '算法', description: null, created_at: '' },
]

function notebook(id: string, courseId: string, title: string): NotebookSummary {
  return { id, course_id: courseId, title, tree_slot: 0, display_order: 0, order_revision: 0,
    is_default: false, created_at: '', updated_at: '' }
}

const currentNotebooks = [notebook('n1', 'c1', '软件设计'), notebook('n2', 'c1', '系统架构')]
const otherNotebooks = [notebook('n3', 'c2', '算法基础')]

function renderPicker(overrides: Partial<Parameters<typeof NoteScopePicker>[0]> = {}) {
  const loadNotebooks = vi.fn(async (courseId: string) => (courseId === 'c2' ? otherNotebooks : []))
  const onPick = vi.fn()
  const onClose = vi.fn()
  render(
    <NoteScopePicker
      open
      courses={courses}
      currentCourseId="c1"
      currentNotebooks={currentNotebooks}
      loadNotebooks={loadNotebooks}
      onPick={onPick}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { loadNotebooks, onPick, onClose }
}

test('选择框列出当前课程 Notebook，并提供课程筛选与名称搜索', () => {
  renderPicker()
  expect(screen.getByLabelText('按课程筛选笔记')).toBeTruthy()
  expect(screen.getByLabelText('搜索笔记名称')).toBeTruthy()
  expect(screen.getByText('软件设计')).toBeTruthy()
  expect(screen.getByText('系统架构')).toBeTruthy()
  expect(screen.getByText('共 2 本')).toBeTruthy()
})

test('换课程时按需拉取该课程 Notebook', async () => {
  const { loadNotebooks } = renderPicker()
  const select = screen.getByLabelText('按课程筛选笔记') as HTMLSelectElement

  fireEvent.change(select, { target: { value: 'c2' } })

  await waitFor(() => expect(loadNotebooks).toHaveBeenCalledWith('c2'))
  await waitFor(() => expect(screen.getByText('算法基础')).toBeTruthy())
  expect(screen.queryByText('软件设计')).toBeNull()
})

test('按名称搜索过滤笔记', () => {
  renderPicker()
  const input = screen.getByLabelText('搜索笔记名称') as HTMLInputElement

  fireEvent.change(input, { target: { value: '软件' } })
  expect(screen.getByText('软件设计')).toBeTruthy()
  expect(screen.queryByText('系统架构')).toBeNull()

  fireEvent.change(input, { target: { value: '不存在的词' } })
  expect(screen.getByText('没有匹配的 Notebook，换个词试试')).toBeTruthy()
})

test('选中 Notebook 后回传并交给父级关闭', () => {
  const { onPick } = renderPicker()
  fireEvent.click(screen.getByText('软件设计'))
  expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'n1', title: '软件设计' }))
})

test('Esc 关闭选择框', () => {
  const { onClose } = renderPicker()
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(onClose).toHaveBeenCalled()
})
