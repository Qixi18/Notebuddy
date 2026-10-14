import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { HomePage } from '../src/pages/HomePage'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
vi.mock('../src/api', () => ({ api: { getForest: async () => ({ courses: Array.from({ length: 4 }, (_, i) => ({ course_id: `c${i}`, name: `课${i}`, semester: 1, level: 'foundation', position: i, revision: 0, learning_state: 'planned', prerequisites: [] })) }), getCourseTree: async (id: string) => ({ course_id: id, notebooks: [] }) } }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear() })
function Fixture() {
  const [courses, setCourses] = useState(Array.from({ length: 4 }, (_, i) => ({ id: `c${i}`, name: `课${i}`, created_at: `2026-10-0${i + 1}`, last_opened_at: null })))
  const navigate = useNavigate()
  function visit() { setCourses(current => current.map(course => course.id === 'c0' ? { ...course, last_opened_at: '2026-10-14' } as never : course)) }
  return <WorkspaceProvider value={{ courses, coursesLoading: false } as unknown as WorkspaceContextValue}><Routes><Route path="/" element={<HomePage />} /><Route path="/forest" element={<><button onClick={visit}>访问第四课</button><button onClick={() => navigate(-1)}>浏览器返回</button><button onClick={() => navigate('/')}>主动首页</button></>} /></Routes></WorkspaceProvider>
}
test('browser return restores the three-course collection; an explicit Home recalculates server recency', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1700, height: 720 } as DOMRect)
  const { container } = render(<MemoryRouter><Fixture /></MemoryRouter>)
  await waitFor(() => expect(container.querySelector('[data-course-id="c1"]')).toBeTruthy())
  expect(container.querySelector('[data-course-id="c0"]')).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '走进知识森林' }))
  fireEvent.click(screen.getByRole('button', { name: '访问第四课' }))
  fireEvent.click(screen.getByRole('button', { name: '浏览器返回' }))
  await waitFor(() => expect(container.querySelector('[data-course-id="c1"]')).toBeTruthy())
  expect(container.querySelector('[data-course-id="c0"]')).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '走进知识森林' }))
  fireEvent.click(screen.getByRole('button', { name: '主动首页' }))
  await waitFor(() => expect(container.querySelector('[data-course-id="c0"]')).toBeTruthy())
  expect(container.querySelector('[data-course-id="c1"]')).toBeNull()
})
