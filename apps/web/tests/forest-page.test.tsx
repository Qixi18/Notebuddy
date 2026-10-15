import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { ForestPage } from '../src/pages/ForestPage'
vi.mock('../src/components/AppLayout', () => ({ useWorkspace: () => ({ refreshCourses: vi.fn() }) }))
vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn(), getCourseTree: vi.fn(), searchForest: vi.fn(), listNotes: vi.fn(), getNote: vi.fn(), getLatestForestJob: vi.fn(), retryForestJob: vi.fn() } }))
const courses = Array.from({ length: 60 }, (_, i) => ({ course_id: `c${i}`, name: `课程${i}`, semester: Math.floor(i / 8) + 1, level: 'foundation', learning_state: 'learning', position: i, revision: 0, note_count: 200, material_count: 1, prerequisites: [] }))
const book = (id: string) => ({ id: `b-${id}`, tree_slot: 0, course_id: id, title: `${id}笔记本`, order_revision: 0, chapters: [{ id: `m-${id}`, title: '第一讲', chapter_order: 0, status: 'completed', deleted_at: null, sections: Array.from({ length: 200 }, (_, i) => ({ id: `${id}-note-${i}`, notebook_id: `b-${id}`, tree_slot: i, material_id: `m-${id}`, title: `${id}知识点${i}`, section_order: i, revision_number: 1, user_locked: false, updated_at: '' })) }], historical_sections: [], removed_chapters: [] })
function Reader() { const location = useLocation(), navigate = useNavigate(); return <><p>{location.pathname}{location.search}</p><button onClick={() => navigate('/forest')}>返回森林</button></> }
function renderPage(entry = '/forest') { return render(<MemoryRouter initialEntries={[entry]}><Routes><Route path="/forest" element={<ForestPage />} /><Route path="/courses/:courseId/notebooks/:notebookId" element={<Reader />} /></Routes></MemoryRouter>) }
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); vi.clearAllMocks()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
  vi.mocked(api.getForest).mockResolvedValue({ courses } as never)
  vi.mocked(api.getForestRelations).mockResolvedValue([])
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [book(id)] }) as never)
  vi.mocked(api.getLatestForestJob).mockResolvedValue(null)
})
afterEach(async () => { cleanup(); await new Promise(resolve => setTimeout(resolve, 0)); vi.unstubAllGlobals(); vi.restoreAllMocks() })
test('large forest loads only nearby lightweight directories and opens an exact owned leaf', async () => {
  renderPage('/forest?course=c0')
  const leaf = await screen.findByRole('button', { name: '打开知识点：c0知识点0' })
  expect(api.listNotes).not.toHaveBeenCalled(); expect(api.getNote).not.toHaveBeenCalled()
  expect(vi.mocked(api.getCourseTree).mock.calls.length).toBeLessThan(8)
  expect(api.getCourseTree).not.toHaveBeenCalledWith('c59')
  fireEvent.click(leaf)
  await screen.findByText('/courses/c0/notebooks/b-c0?chapter=m-c0&section=c0-note-0')
  expect(sessionStorage.getItem('notebuddy.scene.forest')).toContain('camera')
})
test('course settings stay separate from the root book menu and preserve multi-book selection', async () => {
  renderPage('/forest?course=c0')
  fireEvent.click(await screen.findByRole('button', { name: '课程菜单：课程0' }))
  expect(screen.getByRole('dialog', { name: '课程0笔记本操作' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '关闭笔记本菜单' }))
  fireEvent.click(screen.getByRole('button', { name: '课程设置' }))
  expect(await screen.findByLabelText('笔记本')).toBeTruthy()
  expect(screen.getByRole('button', { name: '保存课程设置' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '退出课程聚焦' }))
  expect(screen.queryByLabelText('设置课程')).toBeNull()
})
test('confirmed endpoints beyond overview remain visible and connected in the shared scene', async () => {
  vi.mocked(api.getForest).mockResolvedValue({ courses: courses.slice(0, 2) } as never)
  vi.mocked(api.getForestRelations).mockResolvedValue([{ id: 'r', source_course_id: 'c0', target_course_id: 'c1', source_note_id: 'c0-note-18', target_note_id: 'c1-note-18', source_title: 'c0知识点18', target_title: 'c1知识点18', relation_type: 'related', status: 'confirmed', origin: 'manual', stale: false }] as never)
  const { container } = renderPage()
  await waitFor(() => expect(container.querySelector('[data-note-id="c0-note-18"]')).toBeTruthy())
  expect(container.querySelector('[data-note-id="c1-note-18"]')).toBeTruthy()
  expect(container.querySelector('.kt-vine')).toBeTruthy()
})
test('failed automatic relation job is visible on actual focus and remains retryable', async () => {
  vi.mocked(api.getLatestForestJob).mockResolvedValue({ id: 'automatic', status: 'failed', progress: 0, error_message: '模型未配置，请配置后重试' } as never)
  vi.mocked(api.retryForestJob).mockResolvedValue({ id: 'automatic', status: 'completed', progress: 100 } as never)
  renderPage('/forest?course=c0')
  await screen.findByText('模型未配置，请配置后重试')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByText('关联任务已完成')
})
test.each([900, 390])('two returns preserve camera and directory at %ipx', async width => {
  let resize: ResizeObserverCallback
  vi.stubGlobal('ResizeObserver', class { constructor(callback: ResizeObserverCallback) { resize = callback } observe() {} disconnect() {} })
  const measure = (w = width) => act(() => { vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: w, height: 600 } as DOMRect); resize([{ contentRect: { width: w, height: 600 } } as ResizeObserverEntry], {} as ResizeObserver) })
  const { container } = renderPage('/forest?course=c0')
  measure()
  await waitFor(() => expect(container.querySelector('[data-notebook-id="b-c0"]')).toBeTruthy())
  for (let i = 0; i < 2; i++) {
    const focus = screen.queryByRole('button', { name: '聚焦课程：课程0' })
    if (focus) fireEvent.click(focus)
    fireEvent.click(await screen.findByRole('button', { name: '展开c0笔记本的全部200个知识点' }))
    fireEvent.click(await screen.findByRole('button', { name: '第一讲 · c0知识点199' }))
    const saved = JSON.parse(sessionStorage.getItem('notebuddy.scene.forest')!).view
    fireEvent.click(await screen.findByRole('button', { name: '返回森林' }))
    measure(width + 26); measure()
    await screen.findByRole('dialog', { name: '课程0笔记目录' })
    await waitFor(() => expect(container.querySelector('.kt-canvas > g')!.getAttribute('transform')).toBe(`translate(${saved.camera.x},${saved.camera.y}) scale(${saved.camera.k})`))
    fireEvent.click(screen.getByRole('button', { name: '关闭笔记目录' }))
  }
})
