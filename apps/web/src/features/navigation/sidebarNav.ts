export type SidebarNavId =
  | 'home'
  | 'create'
  | 'courses'
  | 'forest'
  | 'recycle'
  | 'assistant'
  | 'settings'

export type SidebarNavItem = {
  id: SidebarNavId
  label: string
  icon: string
}

/** 主导航：数组顺序即侧边栏从上到下的展示顺序。 */
export const primaryNavItems: SidebarNavItem[] = [
  { id: 'home', label: '首页', icon: '⌂' },
  { id: 'courses', label: '课程', icon: '▦' },
  { id: 'forest', label: '知识森林', icon: 'forest' },
  { id: 'assistant', label: '答疑桌宠', icon: '✧' },
  { id: 'recycle', label: '回收站', icon: 'recycle' },
]

/** 底部固定区：与主导航用分隔线隔开。 */
export const footerNavItems: SidebarNavItem[] = [
  { id: 'settings', label: '设置', icon: '⚙' },
]

/**
 * 当前路由对应的侧边栏项。命令型入口（新建、设置）不会成为当前项。
 * 先判定更具体的路由，否则 /courses/:id/assistant 会同时命中「课程」与「答疑桌宠」。
 */
export function resolveActiveNav(pathname: string): SidebarNavId | undefined {
  if (pathname === '/') return 'home'
  if (pathname === '/forest') return 'forest'
  if (pathname === '/recycle') return 'recycle'
  if (pathname.endsWith('/assistant')) return 'assistant'
  if (pathname === '/courses' || pathname.startsWith('/courses/')) return 'courses'
  return undefined
}
