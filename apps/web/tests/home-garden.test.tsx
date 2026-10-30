import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { StrictMode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'

vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn().mockResolvedValue([]), getLatestForestJob: vi.fn().mockResolvedValue(null), getCourseTree: vi.fn().mockResolvedValue({ course_id: 'c', notebooks: [] }) } }))
afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear() })

test('a failed course-tree read can be retried without losing the create-course entry', async () => {
  vi.mocked(api.getForest).mockRejectedValueOnce(new Error('课程树暂时不可用')).mockResolvedValueOnce({ courses: [{ course_id: 'c', name: '离散数学', semester: 1, level: 'foundation', learning_state: 'learning', position: 0, revision: 0, note_count: 0, material_count: 0, prerequisites: [] }] })
  render(<MemoryRouter><WorkspaceProvider value={{ courses: [{ id: 'c', name: '离散数学', description: null, created_at: '' }], coursesLoading: false } as unknown as WorkspaceContextValue}><HomePage /></WorkspaceProvider></MemoryRouter>)
  expect((await screen.findByRole('alert')).textContent).toContain('课程树暂时不可用')
  fireEvent.click(screen.getByRole('button', { name: '重新读取课程树' }))
  await screen.findByRole('button', { name: '课程菜单：离散数学' })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '新建课程', exact: true }))
  expect(screen.getByRole('dialog', { name: '创建课程' })).toBeTruthy()
})

function mountEmptyHome() {
  vi.mocked(api.getForest).mockResolvedValue({ courses: [] })
  render(<StrictMode><MemoryRouter><WorkspaceProvider value={{ courses: [], coursesLoading: false, createCourse: vi.fn(), busy: false } as unknown as WorkspaceContextValue}><HomePage /></WorkspaceProvider></MemoryRouter></StrictMode>)
  const trigger = screen.getByRole('button', { name: '新建课程', exact: true })
  trigger.focus()
  fireEvent.click(trigger)
}

test('the create-course name field receives focus even with StrictMode effect replay', () => {
  mountEmptyHome()
  expect(document.activeElement).toBe(screen.getByLabelText('课程名称'))
})

test('the create-course dialog traps keyboard focus inside the open dialog', () => {
  mountEmptyHome()
  fireEvent.change(screen.getByLabelText('课程名称'), { target: { value: '数学' } })
  const submit = screen.getByRole('button', { name: '创建并打开' })
  submit.focus()
  fireEvent.keyDown(submit, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭' }))
})

test('clicking the create-course backdrop closes the dialog and restores its trigger', () => {
  mountEmptyHome()
  fireEvent.mouseDown(screen.getByRole('dialog', { name: '创建课程' }).parentElement!)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '新建课程', exact: true }))
})
