import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { HomePage } from '../src/pages/HomePage'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { api } from '../src/api'
import type { ForestCourse } from '../src/features/forest/types'

vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getCourseTree: vi.fn(async (id: string) => ({ course_id: id, notebooks: [] })), getForestRelations: vi.fn().mockResolvedValue([]), getLatestForestJob: vi.fn().mockResolvedValue(null) } }))
let rows: ForestCourse[]
const courses = Array.from({ length: 4 }, (_, i) => ({ id: `c${i}`, name: `课${i}`, created_at: `2026-10-0${4-i}`, last_opened_at: i === 0 ? '2027-01-01' : null }))
beforeEach(() => {
  rows = courses.map((course, i) => ({ course_id: course.id, name: course.name, position: i, revision: 0, learning_state: i ? 'learning' : 'planned', semester: null, level: 'unspecified', prerequisites: [], note_count: 0, material_count: 0 }))
  vi.mocked(api.getForest).mockImplementation(async () => ({ courses: structuredClone(rows) }))
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1700, height: 720 } as DOMRect)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); sessionStorage.clear() })
function Fixture() {
  const navigate = useNavigate()
  return <WorkspaceProvider value={{ courses, coursesLoading: false } as unknown as WorkspaceContextValue}><Routes><Route path="/" element={<HomePage />} /><Route path="/forest" element={<><button onClick={() => { rows = rows.map(row => row.course_id === 'c1' ? { ...row, learning_state: 'planned' } : row.course_id === 'c0' ? { ...row, learning_state: 'learning' } : row) }}>更换首页课程</button><button onClick={() => navigate(-1)}>浏览器返回</button></>} /></Routes></WorkspaceProvider>
}

test('only currently learning courses occupy home, regardless of visits', async () => {
  const { container } = render(<MemoryRouter><Fixture /></MemoryRouter>)
  await waitFor(() => expect(container.querySelectorAll('.home-course-card')).toHaveLength(3))
  expect(container.querySelector('[data-course-id="c0"]')).toBeNull()
  expect(container.querySelector('[data-course-id="c1"]')).toBeTruthy()
})

test('returning from the forest honors changed learning membership instead of old home snapshots', async () => {
  const { container } = render(<MemoryRouter><Fixture /></MemoryRouter>)
  await waitFor(() => expect(container.querySelector('[data-course-id="c1"]')).toBeTruthy())
  fireEvent.click(screen.getByRole('link', { name: '走进知识森林' }))
  fireEvent.click(screen.getByRole('button', { name: '更换首页课程' }))
  fireEvent.click(screen.getByRole('button', { name: '浏览器返回' }))
  await waitFor(() => expect(container.querySelector('[data-course-id="c0"]')).toBeTruthy())
  expect(container.querySelector('[data-course-id="c1"]')).toBeNull()
})

test('an empty learning selection invites choosing trees rather than filling with unrelated courses', async () => {
  rows = rows.map(row => ({ ...row, learning_state: 'planned' }))
  const { container } = render(<MemoryRouter><Fixture /></MemoryRouter>)
  await screen.findByRole('link', { name: '选择首页课程' })
  expect(container.querySelectorAll('.home-course-card')).toHaveLength(0)
})
