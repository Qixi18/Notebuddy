import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { createMemoryRouter, matchRoutes, RouterProvider } from 'react-router-dom'

import { appRoutes } from '../src/App'
import { AppLayout, WorkspaceProvider, type WorkspaceContextValue } from '../src/components/AppLayout'

afterEach(cleanup)

test('data-router route tree keeps primary and legacy URLs addressable', () => {
  expect(matchRoutes(appRoutes, '/')?.at(-1)?.route.index).toBe(true)
  expect(matchRoutes(appRoutes, '/forest')?.at(-1)?.route.path).toBe('/forest')
  expect(matchRoutes(appRoutes, '/recycle')?.at(-1)?.route.path).toBe('/recycle')
  expect(matchRoutes(appRoutes, '/courses/c/notebooks/n')?.at(-1)?.route.path)
    .toBe('/courses/:courseId/notebooks/:notebookId')
  expect(matchRoutes(appRoutes, '/notebooks/unbound/n')?.at(-1)?.route.path)
    .toBe('/notebooks/unbound/:notebookId')
  expect(matchRoutes(appRoutes, '/courses/c/materials')?.at(-1)?.route.path)
    .toBe('/courses/:courseId/materials')
  expect(matchRoutes(appRoutes, '/courses/c/notes/n')?.at(-1)?.route.path)
    .toBe('/courses/:courseId/notes/:noteId')
})

function renderWorkspace(initialEntry: string, documentDirty = false) {
  const setDocumentDirty = vi.fn()
  const setEditingNote = vi.fn()
  const workspace = {
    courses: [],
    error: undefined,
    setError: vi.fn(),
    noteDirty: false,
    documentDirty,
    setDocumentDirty,
    setEditingNote,
  } as unknown as WorkspaceContextValue
  const router = createMemoryRouter([{
    element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider>,
    children: [
      { path: '/courses/c/notebooks/n', element: <p>Notebook 页面</p> },
      { path: '/forest', element: <p>知识森林页面</p> },
      { path: '/recycle', element: <p>回收站页面</p> },
    ],
  }], { initialEntries: [initialEntry] })

  render(<RouterProvider router={router} />)
  return { router, setDocumentDirty, setEditingNote }
}

test('Notebook 页面内点击侧栏能切换到森林和回收站', async () => {
  const { router } = renderWorkspace('/courses/c/notebooks/n')

  fireEvent.click(screen.getByRole('button', { name: '知识森林' }))
  expect(await screen.findByText('知识森林页面')).toBeTruthy()
  await waitFor(() => expect(router.state.location.pathname).toBe('/forest'))

  fireEvent.click(screen.getByRole('button', { name: '回收站' }))
  expect(await screen.findByText('回收站页面')).toBeTruthy()
  await waitFor(() => expect(router.state.location.pathname).toBe('/recycle'))
})

test('脏 Notebook 离开时等待确认，确认后完成侧栏跳转', async () => {
  const { router, setDocumentDirty, setEditingNote } = renderWorkspace('/courses/c/notebooks/n', true)

  fireEvent.click(screen.getByRole('button', { name: '知识森林' }))
  expect(await screen.findByRole('heading', { name: '离开正在编辑的笔记？' })).toBeTruthy()
  expect(router.state.location.pathname).toBe('/courses/c/notebooks/n')

  fireEvent.click(screen.getByRole('button', { name: '放弃草稿并离开' }))
  expect(await screen.findByText('知识森林页面')).toBeTruthy()
  expect(setDocumentDirty).toHaveBeenCalledWith(false)
  expect(router.state.location.pathname).toBe('/forest')
})
