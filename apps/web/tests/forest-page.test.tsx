import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { ForestPage } from '../src/pages/ForestPage'
import { FOREST_VIEW_KEY } from '../src/features/forest/navigation'

vi.mock('../src/components/AppLayout', () => ({
  useWorkspace: () => ({ refreshCourses: vi.fn() }),
}))
vi.mock('../src/api', () => ({
  api: {
    getForest: vi.fn(),
    getForestRelations: vi.fn(),
    getNotebook: vi.fn(),
    searchForest: vi.fn(),
    listNotes: vi.fn(),
    getNote: vi.fn(),
    getLatestForestJob: vi.fn(),
    retryForestJob: vi.fn(),
  },
}))
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
    window.setTimeout(() => callback(0), 0),
  )
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
})
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
  vi.unstubAllGlobals()
})
const courses = Array.from({ length: 60 }, (_, i) => ({
  course_id: `c${i}`,
  name: `课程${i}`,
  semester: Math.floor(i / 8) + 1,
  level: 'foundation',
  learning_state: i < 3 ? 'learning' : 'planned',
  position: i,
  revision: 0,
  note_count: i < 3 ? 200 : 0,
  material_count: i < 3 ? 1 : 0,
  prerequisites: [],
}))
const book = (id: string) => ({
  course_id: id,
  title: id,
  order_revision: 0,
  chapters: [
    {
      id: `m-${id}`,
      title: '第一讲',
      chapter_order: 0,
      status: 'completed',
      deleted_at: null,
      sections: Array.from({ length: 200 }, (_, i) => ({
        id: `${id}-note-${i}`,
        material_id: `m-${id}`,
        title: `${id}知识点${i}`,
        section_order: i,
        revision_number: 1,
        knowledge_node_id: `k${i}`,
        section_key: null,
        user_locked: false,
        updated_at: '',
      })),
    },
  ],
  historical_sections: [],
  removed_chapters: [],
})
function setup() {
  vi.mocked(api.getForest).mockResolvedValue({ courses: courses as never })
  vi.mocked(api.getForestRelations).mockResolvedValue([])
  vi.mocked(api.getNotebook).mockImplementation(async (id) => book(id) as never)
  vi.mocked(api.getLatestForestJob).mockResolvedValue(null)
}
function Reader() {
  const location = useLocation(),
    navigate = useNavigate()
  return (
    <>
      <p>
        {location.pathname}
        {location.search}
      </p>
      <button onClick={() => navigate('/forest')}>返回森林</button>
    </>
  )
}
const renderPage = (entry = '/forest') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/forest" element={<ForestPage />} />
        <Route path="/courses/:courseId/notebook" element={<Reader />} />
      </Routes>
    </MemoryRouter>,
  )

test('large forest loads only nearby outlines and a leaf opens its independent section', async () => {
  setup()
  renderPage()
  const leaf = await screen.findByRole('button', { name: '打开笔记：c0知识点0' })
  expect(api.listNotes).not.toHaveBeenCalled()
  expect(api.getNote).not.toHaveBeenCalled()
  expect(vi.mocked(api.getNotebook).mock.calls.length).toBeLessThan(7)
  expect(api.getNotebook).not.toHaveBeenCalledWith('c59')
  fireEvent.click(leaf)
  await screen.findByText('/courses/c0/notebook?chapter=m-c0&section=c0-note-0')
  expect(sessionStorage.getItem(FOREST_VIEW_KEY)).toContain('camera')
})

test('exiting query-selected course focus removes its panel and expanded tree', async () => {
  setup()
  const { container } = renderPage('/forest?course=c0')
  fireEvent.click(await screen.findByRole('button', { name: '退出课程聚焦' }))
  await waitFor(() => {
    expect(screen.queryByRole('button', { name: '退出课程聚焦' })).toBeNull()
    expect(container.querySelector('.forest-tree-focused')).toBeNull()
  })
})

test('confirmed relation endpoints beyond the overview remain visible and connected', async () => {
  setup()
  vi.mocked(api.getForestRelations).mockResolvedValue([
    {
      id: 'r',
      source_course_id: 'c0',
      target_course_id: 'c1',
      source_note_id: 'c0-note-18',
      target_note_id: 'c1-note-18',
      source_title: 'c0知识点18',
      target_title: 'c1知识点18',
      source_course_name: '课程0',
      target_course_name: '课程1',
      relation_type: 'related',
      reason: '真实来源',
      status: 'confirmed',
      origin: 'manual',
      source_revision: 1,
      target_revision: 1,
      stale: false,
      source_ref_ids: [],
      target_ref_ids: [],
    },
  ] as never)
  renderPage()
  await screen.findByRole('button', { name: '跨课程关联：c0知识点18与c1知识点18' })
  expect(screen.getByRole('button', { name: '打开笔记：c0知识点18' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '打开笔记：c1知识点18' })).toBeTruthy()
})

test('return from a leaf preserves focused chapter and camera', async () => {
  setup()
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '聚焦课程：课程0' }))
  await screen.findByRole('button', { name: '退出课程聚焦' })
  fireEvent.click(screen.getByRole('button', { name: '向右移动森林视口' }))
  fireEvent.click(screen.getByRole('button', { name: 'c0知识点0' }))
  const saved = sessionStorage.getItem(FOREST_VIEW_KEY)
  fireEvent.click(await screen.findByRole('button', { name: '返回森林' }))
  await screen.findByRole('button', { name: '退出课程聚焦' })
  await waitFor(() => expect(sessionStorage.getItem(FOREST_VIEW_KEY)).toEqual(saved))
  expect(
    (await screen.findByRole('button', { name: /第一讲.*200/ })).getAttribute('aria-expanded'),
  ).toBe('true')
})

test('an automatically queued failed relation job is visible on focus and can be retried', async () => {
  setup()
  vi.mocked(api.getLatestForestJob).mockResolvedValue({
    id: 'automatic',
    kind: 'cross_course_relations',
    status: 'failed',
    progress: 0,
    error_message: '模型未配置，请配置后重试',
  } as never)
  vi.mocked(api.retryForestJob).mockResolvedValue({
    id: 'automatic',
    kind: 'cross_course_relations',
    status: 'completed',
    progress: 100,
    error_message: null,
  } as never)
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: '聚焦课程：课程0' }))
  await screen.findByText('模型未配置，请配置后重试')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(api.retryForestJob).toHaveBeenCalledWith('automatic'))
})

test('a focused tree recenters when the desktop viewport becomes narrow', async () => {
  setup()
  let resize: ResizeObserverCallback
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        resize = callback
      }
      observe() {}
      disconnect() {}
    },
  )
  const { container } = renderPage()
  act(() =>
    resize(
      [{ contentRect: { width: 1200, height: 850 } } as ResizeObserverEntry],
      {} as ResizeObserver,
    ),
  )
  fireEvent.click(await screen.findByRole('button', { name: '聚焦课程：课程0' }))
  await screen.findByRole('button', { name: '退出课程聚焦' })
  act(() =>
    resize(
      [{ contentRect: { width: 390, height: 700 } } as ResizeObserverEntry],
      {} as ResizeObserver,
    ),
  )
  await waitFor(() => {
    const scene = container.querySelector('.forest-canvas > g')!
    const transform = scene
      .getAttribute('transform')!
      .match(/translate\(([^,]+),([^)]+)\) scale\(([^)]+)\)/)!
    const tree = container.querySelector('.forest-tree-focused')!
    const x = Number(tree.getAttribute('transform')!.match(/translate\(([^,]+)/)![1])
    expect(Number(transform[1]) + x * Number(transform[3])).toBeCloseTo(195)
  })
})

test.each([900, 390])(
  'returning twice to a measured %ipx forest preserves the saved camera',
  async (width) => {
    setup()
    let resize: ResizeObserverCallback
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          resize = callback
        }
        observe() {}
        disconnect() {}
      },
    )
    const measure = () =>
      act(() =>
        resize(
          [{ contentRect: { width, height: 600 } } as ResizeObserverEntry],
          {} as ResizeObserver,
        ),
      )
    const { container } = renderPage()
    measure()
    fireEvent.click(await screen.findByRole('button', { name: '聚焦课程：课程0' }))
    await screen.findByRole('button', { name: '退出课程聚焦' })
    fireEvent.click(screen.getByRole('button', { name: '向右移动森林视口' }))
    for (let visit = 0; visit < 2; visit++) {
      fireEvent.click(await screen.findByRole('button', { name: 'c0知识点0' }))
      const saved = JSON.parse(sessionStorage.getItem(FOREST_VIEW_KEY)!).camera
      fireEvent.click(await screen.findByRole('button', { name: '返回森林' }))
      measure()
      await screen.findByRole('button', { name: '退出课程聚焦' })
      const transform = container.querySelector('.forest-canvas > g')!.getAttribute('transform')
      expect(transform).toBe(`translate(${saved.x},${saved.y}) scale(${saved.k})`)
    }
  },
)

test('transient layout widths on return do not shift a camera saved for the stable viewport', async () => {
  setup()
  let resize: ResizeObserverCallback
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: ResizeObserverCallback) {
        resize = callback
      }
      observe() {}
      disconnect() {}
    },
  )
  const measure = (width: number) =>
    act(() =>
      resize(
        [{ contentRect: { width, height: 523 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      ),
    )
  const { container } = renderPage()
  measure(664)
  fireEvent.click(await screen.findByRole('button', { name: '聚焦课程：课程0' }))
  await screen.findByRole('button', { name: '退出课程聚焦' })
  fireEvent.click(screen.getByRole('button', { name: '向右移动森林视口' }))
  for (let visit = 0; visit < 2; visit++) {
    fireEvent.click(await screen.findByRole('button', { name: 'c0知识点0' }))
    const saved = JSON.parse(sessionStorage.getItem(FOREST_VIEW_KEY)!).camera
    fireEvent.click(await screen.findByRole('button', { name: '返回森林' }))
    measure(690)
    measure(664)
    await screen.findByRole('button', { name: '退出课程聚焦' })
    expect(container.querySelector('.forest-canvas > g')!.getAttribute('transform')).toBe(
      `translate(${saved.x},${saved.y}) scale(${saved.k})`,
    )
  }
})
