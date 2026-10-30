import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../src/api'
import { WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'
import { HomePage } from '../src/pages/HomePage'
import { ForestPage } from '../src/pages/ForestPage'

vi.mock('../src/api', () => ({ api: { getForest: vi.fn(), getForestRelations: vi.fn(), getCourseTree: vi.fn(), getLatestForestJob: vi.fn().mockResolvedValue(null) } }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); sessionStorage.clear() })
function Navigation() {
  const location = useLocation(), navigate = useNavigate()
  return <><output aria-label="当前位置">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>浏览器返回</button></>
}

test('home relation directory enters the full forest and return preserves the learning course collection', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 1700, height: 720 } as DOMRect)
  const courses = Array.from({ length: 4 }, (_, index) => ({ id: `c${index}`, course_id: `c${index}`, name: `课${index}`, created_at: `2026-10-0${index + 1}`, last_opened_at: null, position: index, semester: 1, level: 'foundation', learning_state: index === 0 ? 'planned' : 'learning', prerequisites: [], revision: 0, note_count: 1 }))
  const relation = (id: string, source: number, target: number) => ({ id, source_course_id: `c${source}`, target_course_id: `c${target}`, source_notebook_id: `c${source}-book`, target_notebook_id: `c${target}-book`, source_block_id: `c${source}-note`, target_block_id: `c${target}-note`, source_title: `课${source}点`, target_title: `课${target}点`, source_course_name: `课${source}`, target_course_name: `课${target}`, relation_type: 'related', status: 'confirmed', origin: 'ai', activation_mode: 'automatic', stale: false, source_ref_ids: [], target_ref_ids: [] })
  vi.mocked(api.getForest).mockResolvedValue({ courses } as never)
  vi.mocked(api.getForestRelations).mockResolvedValue([relation('outside', 0, 1), relation('home', 2, 3)] as never)
  vi.mocked(api.getCourseTree).mockImplementation(async id => ({ course_id: id, notebooks: [{ id: `${id}-book`, course_id: id, title: `${id}本`, tree_slot: 0, order_revision: 0, chapters: [{ id: `${id}-material`, status: 'completed', sections: [{ id: `${id}-note`, block_id: `${id}-note`, notebook_id: `${id}-book`, title: `课${id.slice(1)}点`, tree_slot: 0, material_id: `${id}-material` }] }], historical_sections: [] }] }) as never)
  const { container } = render(<MemoryRouter><WorkspaceProvider value={{ courses, coursesLoading: false, refreshCourses: vi.fn() } as unknown as WorkspaceContextValue}><Routes><Route path="/" element={<HomePage />} /><Route path="/forest" element={<ForestPage />} /></Routes><Navigation /></WorkspaceProvider></MemoryRouter>)
  await screen.findByRole('button', { name: '查看知识关联 ↗' })
  await screen.findByRole('button', { name: '打开知识点：课3点' })
  await screen.findByRole('button', { name: '打开知识点：课1点' })
  const savedTree = container.querySelector('.home-course-tree')!.getAttribute('viewBox')
  expect(container.querySelector('[data-course-id="c0"]')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看知识关联 ↗' }))
  fireEvent.click(screen.getAllByRole('button', { name: '在树中定位端点' })[0])
  await waitFor(() => expect(screen.getByLabelText('当前位置').textContent).toBe('/forest?relation=outside'))
  await waitFor(() => expect(container.querySelector('.kt-vine-selected')).toBeTruthy())
  expect([...container.querySelectorAll('[data-note-id]')].find(node => node.getAttribute('data-note-id') === JSON.stringify(['c0-book', 'c0-note']))).toBeTruthy()
  expect([...container.querySelectorAll('[data-note-id]')].find(node => node.getAttribute('data-note-id') === JSON.stringify(['c1-book', 'c1-note']))).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '浏览器返回' }))
  await waitFor(() => expect(screen.getByLabelText('当前位置').textContent).toBe('/'))
  await screen.findByRole('button', { name: '查看知识关联 ↗' })
  await screen.findByRole('button', { name: '打开知识点：课3点' })
  await screen.findByRole('button', { name: '打开知识点：课1点' })
  expect(container.querySelector('[data-course-id="c0"]')).toBeNull()
  expect(container.querySelector('.home-course-tree')!.getAttribute('viewBox')).toBe(savedTree)
})
