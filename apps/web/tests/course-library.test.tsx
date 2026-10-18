import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

const createCourse = vi.hoisted(() => vi.fn())

vi.mock('../src/components/AppLayout', () => ({
  useWorkspace: () => ({
    courses: [
      { id: 'c1', name: '科学', description: null, created_at: '2026-10-07T07:07:57.870334', last_opened_at: '2026-10-18T13:00:00.000000' },
      { id: 'c2', name: '历史', description: null, created_at: '2026-10-07T07:07:49.063915', last_opened_at: null },
    ],
    coursesLoading: false,
    createCourse,
    refreshCourses: async () => {},
  }),
}))

import { CourseLibraryPage } from '../src/pages/CourseLibraryPage'

afterEach(() => {
  cleanup()
  createCourse.mockReset()
})

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/courses']}>
      <Routes>
        <Route path="/courses" element={<CourseLibraryPage />} />
        <Route path="/courses/:courseId" element={<div>课程页面</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

test('课程账页按最近打开排序，当前课程带「在读」与继续入口', () => {
  renderPage()
  const rows = Array.from(document.querySelectorAll('.course-ledger-row'))
  expect(rows.map((row) => row.textContent)).toEqual([
    expect.stringContaining('科学'),
    expect.stringContaining('历史'),
  ])
  expect(rows[0]?.className).toContain('course-ledger-row-current')
  expect(rows[0]?.textContent).toContain('在读')
  expect(rows[0]?.textContent).toContain('继续这门课')
  expect(rows[1]?.textContent).toContain('未开始')
})

test('课程行的更多操作按钮打开同一份菜单，触屏无需右键', () => {
  renderPage()
  fireEvent.click(screen.getByRole('button', { name: '打开科学的更多操作' }))
  expect(screen.getByRole('menu')).toBeTruthy()
  expect(screen.getByRole('menuitem', { name: '重命名' })).toBeTruthy()
  expect(screen.getByRole('menuitem', { name: '删除课程' })).toBeTruthy()
})

test('新建课程从侧栏完成：示例名可填入，提交后进入课程页', async () => {
  createCourse.mockResolvedValue({ id: 'c3', name: '软件工程', description: null, created_at: '2026-10-18T13:10:00.000000' })
  renderPage()

  fireEvent.click(screen.getAllByRole('button', { name: /新建课程/ })[0]!)
  expect(screen.getByRole('dialog')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '软件工程' }))
  const input = screen.getByLabelText('课程名称') as HTMLInputElement
  expect(input.value).toBe('软件工程')

  fireEvent.click(screen.getByRole('button', { name: /创建并打开/ }))
  await waitFor(() => expect(createCourse).toHaveBeenCalledWith('软件工程'))
  expect(await screen.findByText('课程页面')).toBeTruthy()
})
