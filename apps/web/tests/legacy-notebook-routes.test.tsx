import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

const apiState = vi.hoisted(() => ({ listNotebooks: vi.fn() }))
vi.mock('../src/api', () => ({ api: { listNotebooks: apiState.listNotebooks } }))

import { LegacyNotebookRedirect } from '../src/features/notebook-workspace/LegacyNotebookRedirect'

function LocationText() {
  const location = useLocation()
  return <p>{location.pathname}{location.search}</p>
}

function mount(path: string) {
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/courses/:courseId/notebook" element={<LegacyNotebookRedirect />} />
    <Route path="/legacy" element={<LegacyNotebookRedirect />} />
    <Route path="/courses/:courseId/notebooks/:notebookId" element={<LocationText />} />
    <Route path="/courses/:courseId" element={<LocationText />} />
    <Route path="/courses" element={<LocationText />} />
  </Routes></MemoryRouter>)
}

beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)

test('requested Notebook is selected and chapter parameters are preserved', async () => {
  apiState.listNotebooks.mockResolvedValue([
    { id: 'a', course_id: 'c', is_default: true },
    { id: 'b', course_id: 'c', is_default: false },
  ])
  mount('/courses/c/notebook?notebook=b&chapter=material-1&section=block-2')
  expect(await screen.findByText('/courses/c/notebooks/b?chapter=material-1&section=block-2')).toBeTruthy()
})

test('missing Notebook parameter chooses the default instead of an arbitrary first item', async () => {
  apiState.listNotebooks.mockResolvedValue([
    { id: 'first', course_id: 'c', is_default: false },
    { id: 'default', course_id: 'c', is_default: true },
  ])
  mount('/courses/c/notebook')
  expect(await screen.findByText('/courses/c/notebooks/default')).toBeTruthy()
})

test('a requested Notebook from another course falls back to the course overview', async () => {
  apiState.listNotebooks.mockResolvedValue([
    { id: 'foreign', course_id: 'other-course', is_default: true },
  ])
  mount('/courses/c/notebook?notebook=foreign')
  expect(await screen.findByText('/courses/c')).toBeTruthy()
})

test('missing courses and courses without Notebooks use safe destinations', async () => {
  mount('/legacy')
  expect(await screen.findByText('/courses')).toBeTruthy()
  apiState.listNotebooks.mockResolvedValue([])
  mount('/courses/empty/notebook')
  expect(await screen.findByText('/courses/empty')).toBeTruthy()
})
