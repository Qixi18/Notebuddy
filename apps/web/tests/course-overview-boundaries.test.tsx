import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { CourseOverviewPage } from '../src/pages/CourseOverviewPage'

vi.mock('../src/api', () => ({ api: { getCourseOverview: vi.fn() } }))
vi.mock('../src/components/AppLayout', async () => ({ useWorkspace: () => {
  const { courseId } = useParams()
  return { course: { id: courseId, name: courseId }, materials: [], coursesLoading: false, courseContentLoading: false }
} }))
vi.mock('../src/pages/CourseKnowledgeStructure', () => ({ CourseKnowledgeStructure: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

function Harness() {
  const navigate = useNavigate()
  return <><button onClick={() => navigate('/courses/second')}>切换课程</button><CourseOverviewPage /></>
}
function mount() {
  render(<MemoryRouter initialEntries={['/courses/first']}><Routes><Route path="/courses/:courseId" element={<Harness />} /></Routes></MemoryRouter>)
}
const first = { counts: { materials: 0, sections: 0, materials_needing_attention: 0 }, notebooks: [{ id: 'old-book', title: '第一门的笔记本' }] }

test('changing course clears the previous notebook directory while the next request loads', async () => {
  vi.mocked(api.getCourseOverview).mockResolvedValueOnce(first as never).mockReturnValueOnce(new Promise(() => {}))
  mount()
  await screen.findByRole('link', { name: '第一门的笔记本 · 继续阅读' })
  fireEvent.click(screen.getByRole('button', { name: '切换课程' }))
  expect(screen.queryByRole('link', { name: '第一门的笔记本 · 继续阅读' })).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('正在读取笔记本')
})

test('a failed course overview can be retried on the same page', async () => {
  vi.mocked(api.getCourseOverview).mockRejectedValueOnce(new Error('课程概览暂不可用')).mockResolvedValueOnce(first as never)
  mount()
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: '重新读取课程概览' }))
  expect(await screen.findByRole('link', { name: '第一门的笔记本 · 继续阅读' })).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})
