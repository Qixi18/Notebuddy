import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

vi.mock('../src/features/assistant/AssistantDock', () => ({ AssistantDock: () => null }))
vi.mock('../src/components/SettingsPanel', () => ({ SettingsPanel: () => <div data-testid="settings-panel" /> }))

import { AppLayout, WorkspaceProvider } from '../src/components/AppLayout'
import { primaryNavItems } from '../src/features/navigation/sidebarNav'

afterEach(cleanup)

const workspace = {
  courseId: 'c1',
  courses: [{ id: 'c1', name: '软件工程', created_at: '2026-01-01T00:00:00Z' }],
  error: undefined,
  setError: () => {},
  noteDirty: false,
  setEditingNote: () => {},
} as never

function renderSidebar(initialEntry: string) {
  const router = createMemoryRouter(
    [{ path: '*', element: <WorkspaceProvider value={workspace}><AppLayout /></WorkspaceProvider> }],
    { initialEntries: [initialEntry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

test('主导航按约定顺序渲染，设置不在主导航内', () => {
  renderSidebar('/')
  const nav = screen.getByRole('navigation', { name: '主导航' })
  expect(within(nav).getAllByRole('button').map((button) => button.textContent)).toEqual(
    primaryNavItems.map((item) => `${item.icon}${item.label}`),
  )
  expect(within(nav).queryByRole('button', { name: '打开设置' })).toBeNull()
  expect(screen.getByRole('button', { name: '打开设置' })).toBeTruthy()
})

test('激活态跟随路由，未命中的项不带 aria-current', () => {
  renderSidebar('/')
  expect(screen.getByRole('button', { name: '首页' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('button', { name: '课程' }).getAttribute('aria-current')).toBeNull()
})

test('知识森林路由高亮森林而不是首页', () => {
  renderSidebar('/forest')
  expect(screen.getByRole('button', { name: '知识森林' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('button', { name: '首页' }).getAttribute('aria-current')).toBeNull()
})

test('课程内页面归属课程，答疑页归属答疑桌宠', () => {
  renderSidebar('/courses/c1/notebook')
  expect(screen.getByRole('button', { name: '课程' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('button', { name: '答疑桌宠' }).getAttribute('aria-current')).toBeNull()
  cleanup()
  renderSidebar('/courses/c1/assistant')
  expect(screen.getByRole('button', { name: '答疑桌宠' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('button', { name: '课程' }).getAttribute('aria-current')).toBeNull()
})

test('回收站是可停留页面：点击后跳转并高亮', () => {
  const router = renderSidebar('/')
  fireEvent.click(screen.getByRole('button', { name: '回收站' }))
  expect(router.state.location.pathname).toBe('/recycle')
  expect(screen.getByRole('button', { name: '回收站' }).getAttribute('aria-current')).toBe('page')
})

test('答疑桌宠进入当前课程的答疑页', () => {
  const router = renderSidebar('/')
  fireEvent.click(screen.getByRole('button', { name: '答疑桌宠' }))
  expect(router.state.location.pathname).toBe('/courses/c1/assistant')
})

test('新建与设置是命令：设置打开面板但不改变路由，新建跳课程页且不占用激活态', () => {
  const router = renderSidebar('/')
  fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
  expect(screen.getByTestId('settings-panel')).toBeTruthy()
  expect(router.state.location.pathname).toBe('/')

  fireEvent.click(screen.getByRole('button', { name: '新建' }))
  expect(router.state.location.pathname).toBe('/courses')
  expect(screen.getByRole('button', { name: '新建' }).getAttribute('aria-current')).toBeNull()
})

test('侧边栏页脚只剩设置，本地状态说明已移除', () => {
  renderSidebar('/')
  const footer = document.querySelector('.sidebar-footer')
  expect(footer).toBeTruthy()
  expect(footer?.querySelector('.local-status-dot')).toBeNull()
  expect(footer?.querySelectorAll('button').length).toBe(1)
  expect(footer?.textContent).toBe('⚙设置')
  expect(document.body.textContent).not.toContain('本地学习空间')
})

test('收起侧边栏按钮在侧边栏顶部一行的右端，是方形纯图标按钮', () => {
  renderSidebar('/')
  const toggle = screen.getByRole('button', { name: '收起侧边栏' })
  // 按钮处在顶部那一行（与品牌块并列），而不是品牌块下方
  expect(toggle.closest('.sidebar-header')).toBeTruthy()
  expect(toggle.parentElement?.firstElementChild?.className).toContain('brand-lockup')
  // 无文字：可见内容只有方向图标
  expect(toggle.textContent).toBe('‹')
  expect(toggle.getAttribute('aria-expanded')).toBe('true')

  fireEvent.click(toggle)
  const expand = screen.getByRole('button', { name: '展开侧边栏' })
  expect(expand.textContent).toBe('›')
  expect(expand.getAttribute('aria-expanded')).toBe('false')
  // 复原，避免收起状态泄漏到同文件后续用例
  fireEvent.click(expand)
  expect(screen.getByRole('button', { name: '收起侧边栏' })).toBeTruthy()
})
