import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

const { createCourse, listNotebooks, createNotebook } = vi.hoisted(() => ({ createCourse: vi.fn(), listNotebooks: vi.fn(), createNotebook: vi.fn() }))

vi.mock('../src/api', () => ({ api: { listNotebooks, createNotebook } }))
vi.mock('../src/components/AppLayout', () => {
  const courses = [
    { id: 'math', name: '数学分析', description: null, created_at: '2026-10-07T07:07:57' },
    { id: 'physics', name: '大学物理', description: null, created_at: '2026-10-07T07:07:49' },
  ]
  return { useWorkspace: () => ({
    courses,
    coursesLoading: false,
    createCourse,
  }) }
})

import { CourseLibraryPage } from '../src/pages/CourseLibraryPage'

afterEach(() => { cleanup(); createCourse.mockReset(); listNotebooks.mockReset(); createNotebook.mockReset() })

function renderPage(initialEntry: string | { pathname: string; state: object } = '/courses') {
  render(<MemoryRouter initialEntries={[initialEntry]}>
    <Routes>
      <Route path="/courses" element={<CourseLibraryPage />} />
      <Route path="/courses/:courseId" element={<div>课程页面</div>} />
      <Route path="/courses/:courseId/notebooks/:notebookId" element={<div>笔记页面</div>} />
    </Routes>
  </MemoryRouter>)
}

function mockNotes() {
  listNotebooks.mockImplementation(async (courseId: string) => courseId === 'math'
    ? [{ id: 'n1', course_id: 'math', title: '一元微积分' }, { id: 'n2', course_id: 'math', title: '导数' }]
    : [{ id: 'n3', course_id: 'physics', title: '波动光学' }])
}

test('按课程分组显示真实笔记数量，点击整张卡片进入笔记', async () => {
  mockNotes()
  renderPage()
  const math = await screen.findByRole('region', { name: '数学分析' })
  const physics = screen.getByRole('region', { name: '大学物理' })
  expect(within(math).getByText('2 篇笔记')).toBeTruthy()
  expect(within(physics).getByText('1 篇笔记')).toBeTruthy()
  fireEvent.click(within(math).getByRole('link', { name: '打开笔记：导数' }))
  expect(await screen.findByText('笔记页面')).toBeTruthy()
})

test('搜索笔记名时只显示匹配卡片，搜索课程名时显示该课程全部笔记', async () => {
  mockNotes()
  renderPage()
  await screen.findByRole('link', { name: '打开笔记：导数' })
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索笔记或课程' }), { target: { value: '导数' } })
  expect(screen.getByRole('link', { name: '打开笔记：导数' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '打开笔记：一元微积分' })).toBeNull()
  expect(screen.queryByRole('region', { name: '大学物理' })).toBeNull()
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索笔记或课程' }), { target: { value: '大学物理' } })
  expect(screen.getByRole('link', { name: '打开笔记：波动光学' })).toBeTruthy()
})

test('新建笔记使用现有笔记本接口，创建后进入笔记', async () => {
  mockNotes()
  createNotebook.mockResolvedValue({ id: 'new-note', course_id: 'physics', title: '力学' })
  renderPage()
  await screen.findByRole('link', { name: '打开笔记：导数' })
  fireEvent.click(screen.getByRole('button', { name: '新建笔记' }))
  expect(screen.getByRole('dialog', { name: '新建笔记' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('所属课程'), { target: { value: 'physics' } })
  fireEvent.change(screen.getByLabelText('笔记名称'), { target: { value: '力学' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并打开' }))
  await waitFor(() => expect(createNotebook).toHaveBeenCalledWith('physics', '力学'))
  expect(await screen.findByText('笔记页面')).toBeTruthy()
})

test('侧边栏创建课程状态仍由课程页处理', async () => {
  mockNotes()
  createCourse.mockResolvedValue({ id: 'new', name: '软件工程' })
  renderPage({ pathname: '/courses', state: { openCreateCourse: true } })
  fireEvent.change(await screen.findByLabelText('课程名称'), { target: { value: '软件工程' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并打开' }))
  await waitFor(() => expect(createCourse).toHaveBeenCalledWith('软件工程'))
  expect(await screen.findByText('课程页面')).toBeTruthy()
})
