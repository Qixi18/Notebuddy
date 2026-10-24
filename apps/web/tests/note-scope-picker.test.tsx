import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { NoteScopePicker } from '../src/features/assistant/NoteScopePicker'
import type { Course, Note } from '../src/types'

afterEach(cleanup)

const courses: Course[] = [
  { id: 'c1', name: '软件', description: null, created_at: '' },
  { id: 'c2', name: '算法', description: null, created_at: '' },
]

function note(id: string, courseId: string, title: string): Note {
  return {
    notebook_id: null, tree_slot: 0, material_id: null, section_key: null, section_order: 0,
    id, course_id: courseId, knowledge_node_id: `k-${id}`, title,
    content_markdown: '', content_origin: 'auto', user_locked: false, revision_number: 1,
    created_at: '', updated_at: '',
  }
}

const currentNotes = [note('n1', 'c1', '内聚与耦合'), note('n2', 'c1', '常见设计模式')]
const otherNotes = [note('n3', 'c2', '红黑树笔记')]

function renderPicker(overrides: Partial<Parameters<typeof NoteScopePicker>[0]> = {}) {
  const loadNotes = vi.fn(async (courseId: string) => (courseId === 'c2' ? otherNotes : []))
  const onPick = vi.fn()
  const onClose = vi.fn()
  render(
    <NoteScopePicker
      open
      courses={courses}
      currentCourseId="c1"
      currentNotes={currentNotes}
      loadNotes={loadNotes}
      onPick={onPick}
      onClose={onClose}
      {...overrides}
    />,
  )
  return { loadNotes, onPick, onClose }
}

test('选择框列出当前课程笔记，并提供课程筛选与名称搜索', () => {
  renderPicker()
  expect(screen.getByLabelText('按课程筛选笔记')).toBeTruthy()
  expect(screen.getByLabelText('搜索笔记名称')).toBeTruthy()
  expect(screen.getByText('内聚与耦合')).toBeTruthy()
  expect(screen.getByText('常见设计模式')).toBeTruthy()
  expect(screen.getByText('共 2 篇')).toBeTruthy()
})

test('换课程时按需拉取该课程笔记', async () => {
  const { loadNotes } = renderPicker()
  const select = screen.getByLabelText('按课程筛选笔记') as HTMLSelectElement

  fireEvent.change(select, { target: { value: 'c2' } })

  await waitFor(() => expect(loadNotes).toHaveBeenCalledWith('c2'))
  await waitFor(() => expect(screen.getByText('红黑树笔记')).toBeTruthy())
  /* 当前课程的笔记不在这个池子里 */
  expect(screen.queryByText('内聚与耦合')).toBeNull()
})

test('按名称搜索过滤笔记', () => {
  renderPicker()
  const input = screen.getByLabelText('搜索笔记名称') as HTMLInputElement

  fireEvent.change(input, { target: { value: '耦合' } })
  expect(screen.getByText('内聚与耦合')).toBeTruthy()
  expect(screen.queryByText('常见设计模式')).toBeNull()

  fireEvent.change(input, { target: { value: '不存在的词' } })
  expect(screen.getByText('没有匹配的笔记，换个词试试')).toBeTruthy()
})

test('选中笔记后回传该笔记并关闭', () => {
  const { onPick } = renderPicker()
  fireEvent.click(screen.getByText('内聚与耦合'))
  expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'n1', title: '内聚与耦合' }))
})

test('Esc 关闭选择框', () => {
  const { onClose } = renderPicker()
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(onClose).toHaveBeenCalled()
})
