import { cleanup, render, screen } from '@testing-library/react'
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom'
import { afterEach, expect, test } from 'vitest'

import { RouteErrorPage } from '../src/components/RouteErrorPage'

afterEach(cleanup)

test('route errors show safe copy and never expose the internal message', async () => {
  const router = createMemoryRouter([{
    element: <Outlet />,
    children: [{ path: '/broken', element: <ThrowError />, errorElement: <RouteErrorPage /> }],
  }], { initialEntries: ['/broken'] })
  render(<RouterProvider router={router} />)

  expect(await screen.findByText('页面暂时无法打开，请稍后重试。')).toBeTruthy()
  expect(screen.queryByText(/C:\\|internal-secret|chunk-[\w.-]+\.js/)).toBeNull()
  expect(screen.getByRole('link', { name: '返回首页' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '重新加载' })).toBeTruthy()
})

function ThrowError(): never {
  throw new Error('internal-secret C:\\private\\chunk-123.js')
}
