import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'
import { ForestPage } from '../src/pages/ForestPage'
import { MaterialsPage } from '../src/pages/MaterialsPage'
vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn().mockResolvedValue([]), getCourseTree: vi.fn(), getLatestForestJob: vi.fn().mockResolvedValue(null), getForestJob: vi.fn(), createNotebook: vi.fn(), listNotebooks: vi.fn(), getCapabilities: vi.fn().mockResolvedValue(undefined), listDeletedMaterials: vi.fn().mockResolvedValue([]) } }))
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks(); sessionStorage.clear() })

test.each(['home', 'forest'])('%s root creation reaches the real upload page and returns with only the new branch growing', async mode => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  const course = { id: 'c', name: '课程', created_at: '2026-10-15', last_opened_at: null }
  const old = { id: 'old-book', course_id: 'c', title: '旧笔记本', tree_slot: 0, order_revision: 0, chapters: [{ id: 'm', title: '第一讲', status: 'completed', sections: [{ id: 'old-note', notebook_id: 'old-book', title: '旧知识点', tree_slot: 0, material_id: 'm' }] }], historical_sections: [], removed_chapters: [] }
  const added = { ...old, id: 'new-book', title: '新增笔记本', tree_slot: 1, chapters: [] }
  let created = false
  vi.mocked(api.getForest).mockResolvedValue({ courses: [{ course_id: 'c', name: '课程', semester: 1, position: 0, level: 'foundation', learning_state: 'learning', prerequisites: [], revision: 0 }] } as never)
  vi.mocked(api.getCourseTree).mockImplementation(async () => ({ course_id: 'c', notebooks: structuredClone(created ? [old, added] : [old]) }) as never)
  vi.mocked(api.createNotebook).mockImplementation(async () => { created = true; return added as never })
  vi.mocked(api.listNotebooks).mockImplementation(async () => structuredClone(created ? [old, added] : [old]) as never)
  function HistoryControl() {
    const navigate = useNavigate(), location = useLocation()
    return <><output aria-label="当前页面">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>浏览器返回</button></>
  }
  const { container } = render(<MemoryRouter initialEntries={[mode === 'home' ? '/' : '/forest']}><WorkspaceProvider value={{ course, courses: [course], coursesLoading: false, materials: [], pages: [], refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}>
    <Routes><Route path="/" element={<HomePage />} /><Route path="/forest" element={<ForestPage />} /><Route path="/courses/:courseId/materials" element={<MaterialsPage />} /></Routes><HistoryControl />
  </WorkspaceProvider></MemoryRouter>)
  await screen.findByRole('button', { name: '打开知识点：旧知识点' })
  expect(container.querySelector('.kt-branch-growth')).toBeNull()
  // The SVG updates immediately; the rounded percentage follows on the next frame.
  if (mode === 'forest') {
    const zoomBefore = Number(container.querySelector('.kt-canvas > g')!.getAttribute('transform')!.match(/scale\(([^)]+)\)/)![1]) * 100
    fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
    await waitFor(() => {
    const zoomAfter = Number.parseInt(screen.getByLabelText('知识树缩放').textContent!)
    expect(zoomAfter).toBeGreaterThan(zoomBefore)
    expect(Math.abs(zoomAfter - zoomBefore * 1.2)).toBeLessThanOrEqual(1)
    })
  } else expect(screen.queryByRole('button', { name: '放大知识树' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '课程菜单：课程' }))
  // Root focus may bring the root into view before its menu opens.
  const camera = container.querySelector('.kt-canvas > g')?.getAttribute('transform')
  fireEvent.click(screen.getByRole('button', { name: '新建笔记本' }))
  fireEvent.change(screen.getByLabelText('笔记本名称'), { target: { value: added.title } })
  fireEvent.click(screen.getByRole('button', { name: '创建并上传' }))
  await screen.findByRole('heading', { name: '课程资料' })
  expect(api.createNotebook).toHaveBeenCalledExactlyOnceWith('c', added.title)
  expect(screen.getByLabelText('当前页面').textContent).toBe('/courses/c/materials?notebook=new-book')
  await waitFor(() => expect((screen.getByLabelText('目标笔记本') as HTMLSelectElement).value).toBe(added.id))
  fireEvent.click(screen.getByRole('button', { name: '浏览器返回' }))
  await screen.findByRole('button', { name: '续读笔记本：新增笔记本' })
  const growth = container.querySelectorAll('.kt-branch-growth')
  if (mode === 'forest') {
    expect(growth).toHaveLength(1)
    expect(growth[0].closest('[data-wood-notebook-id]')?.getAttribute('data-wood-notebook-id')).toBe(added.id)
  }
  // Changing the notebook count selects a new crown silhouette. The existing
  // knowledge point keeps its real identity and notebook ownership as it moves.
  const oldLeaf = screen.getByRole('button', { name: '打开知识点：旧知识点' })
  expect(oldLeaf.closest('[data-note-id]')?.getAttribute('data-note-id')).toBe(JSON.stringify(['old-book', 'old-note']))
  expect(oldLeaf.closest('[data-notebook-id]')?.getAttribute('data-notebook-id')).toBe(old.id)
  expect(container.querySelectorAll('.kt-branch[data-notebook-id="old-book"]')).toHaveLength(1)
  expect(container.querySelectorAll('.kt-branch[data-notebook-id="new-book"]')).toHaveLength(1)
  expect(container.querySelector('.kt-canvas > g')?.getAttribute('transform')).toBe(camera)
})
test.each(['home', 'forest'])('%s grows generated Notebook body in the same scene and stops polling when processing finishes', async mode => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1100, height: 720 } as DOMRect)
  let generated = false
  const course = { id: 'c', name: '课程', created_at: '2026-10-15', last_opened_at: null }
  const section = { id: 'real-generated-note', notebook_id: 'book', tree_slot: 0, material_id: 'material', title: '成功生成的知识点' }
  vi.mocked(api.getForest).mockResolvedValue({ courses: [{ course_id: 'c', name: '课程', semester: 1, position: 0, level: 'foundation', learning_state: 'learning', prerequisites: [], revision: 0 }] } as never)
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [{ id: 'book', course_id: id, title: '笔记本', tree_slot: 0, order_revision: 0, processing: !generated, chapters: generated ? [{ id: 'body', title: '正文小节', status: 'parsed', sections: [section] }] : [], historical_sections: [], removed_chapters: [] }] }) as never)
  const { container } = render(<MemoryRouter initialEntries={[mode === 'home' ? '/' : '/forest']}><WorkspaceProvider value={{ courses: [course], coursesLoading: false, refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}>{mode === 'home' ? <HomePage /> : <ForestPage />}</WorkspaceProvider></MemoryRouter>)
  await screen.findByRole('button', { name: '续读笔记本：笔记本' })
  expect(container.querySelector('[data-note-id="real-generated-note"]')).toBeNull()
  if (mode === 'forest') fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
  const camera = container.querySelector('.kt-canvas > g')?.getAttribute('transform')
  const scene = container.querySelector('.knowledge-tree-scene')
  generated = true // The persistent material job has now committed the real directory.
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  const leaf = await screen.findByRole('button', { name: '打开知识点：成功生成的知识点' })
  expect(leaf.closest('[data-note-id]')?.getAttribute('data-note-id')).toBe(JSON.stringify(['book', 'real-generated-note']))
  expect(leaf.closest('[data-notebook-id]')?.getAttribute('data-notebook-id')).toBe('book')
  expect(container.querySelector('.knowledge-tree-scene')).toBe(scene)
  expect(container.querySelector('.kt-canvas > g')?.getAttribute('transform')).toBe(camera)
  const finishedCalls = vi.mocked(api.getCourseTree).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  await waitFor(() => expect(vi.mocked(api.getCourseTree).mock.calls.length).toBe(finishedCalls))
})

test.each(['home', 'forest'])('%s receives automatic vines after background completion without resetting camera', async mode => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1500, height: 720 } as DOMRect)
  const courses = ['a', 'b'].map((id, index) => ({ id, name: id, created_at: '2026-10-15', last_opened_at: null, course_id: id, position: index, semester: 1, level: 'foundation', learning_state: 'learning', prerequisites: [], revision: 0 }))
  vi.mocked(api.getForest).mockResolvedValue({ courses } as never)
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [{ id: id + '-book', course_id: id, title: id, tree_slot: 0, chapters: [{ id: id + '-m', status: 'completed', sections: [{ id: id + '-n', notebook_id: id + '-book', title: id, tree_slot: 0, material_id: id + '-m' }] }], historical_sections: [] }] }) as never)
  vi.mocked(api.getLatestForestJob).mockImplementation(async id => id === 'a' ? { id: 'job', status: 'processing', progress: 10 } as never : null)
  vi.mocked(api.getForestJob).mockResolvedValue({ id: 'job', status: 'completed', progress: 100 } as never)
  let completed = false
  vi.mocked(api.getForestRelations).mockImplementation(async () => completed ? [{ id: 'v', source_course_id: 'a', target_course_id: 'b', source_notebook_id: 'a-book', target_notebook_id: 'b-book', source_block_id: 'a-n', target_block_id: 'b-n', source_title: 'a', target_title: 'b', relation_type: 'related', status: 'confirmed', origin: 'ai', activation_mode: 'automatic', stale: false }] as never : [])
  const { container } = render(<MemoryRouter initialEntries={[mode === 'home' ? '/' : '/forest']}><WorkspaceProvider value={{ courses, coursesLoading: false, refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}>{mode === 'home' ? <HomePage /> : <ForestPage />}</WorkspaceProvider></MemoryRouter>)
  await screen.findByRole('button', { name: '续读笔记本：a' })
  await waitFor(() => expect(api.getLatestForestJob).toHaveBeenCalledWith('a'))
  if (mode === 'forest') fireEvent.click(screen.getByRole('button', { name: '放大知识树' }))
  const scene = container.querySelector('.knowledge-tree-scene')
  const camera = container.querySelector('.kt-canvas > g')?.getAttribute('transform')
  completed = true
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  await screen.findByRole('button', { name: mode === 'home' ? '查看知识关联 ↗' : /查看a与b的模型推断关联/ })
  expect(container.querySelector('.knowledge-tree-scene')).toBe(scene)
  expect(container.querySelector('.kt-canvas > g')?.getAttribute('transform')).toBe(camera)
  const finished = vi.mocked(api.getForestJob).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  expect(vi.mocked(api.getForestJob).mock.calls.length).toBe(finished)
})
