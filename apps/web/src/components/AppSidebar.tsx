import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { readSidebarQuote } from '../features/navigation/sidebarQuote'
import { footerNavItems, primaryNavItems, resolveActiveNav, type SidebarNavId } from '../features/navigation/sidebarNav'
import { readStorage, writeStorage } from '../utils/safeStorage'

function SidebarIcon({ id, fallback }: { id: SidebarNavId; fallback: string }) {
  if (id === 'forest') return <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3 5 12l3 2-5 6 4 3h10l4-3-5-6 3-2-7-9ZM12 23v6M23 12l-3 4 2 2-2 3 2 3h6l2-3-3-3 2-2-6-4ZM25 24v5"/></svg>
  if (id === 'recycle') return <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 9h22M12 9V5h8v4M8 9l1 19h14l1-19M13 14v9M19 14v9"/></svg>
  return <span aria-hidden="true">{fallback}</span>
}

export function AppSidebar({
  isHome,
  collapsed,
  onCollapsedChange,
  onNavigate,
  onCreateCourse,
  onCreateNote,
}: {
  isHome: boolean
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
  onNavigate: (id: SidebarNavId) => void
  onCreateCourse: () => void
  onCreateNote: () => void
}) {
  const location = useLocation()
  const activeNav = resolveActiveNav(location.pathname)
  const [quote, setQuote] = useState(readSidebarQuote)
  const [createOpen, setCreateOpen] = useState(false)
  const createAreaRef = useRef<HTMLDivElement>(null)

  useEffect(() => { writeStorage('notebuddy.sidebar-collapsed', String(collapsed)) }, [collapsed])
  useEffect(() => {
    const refreshQuote = () => setQuote(readSidebarQuote())
    window.addEventListener('notebuddy-settings-changed', refreshQuote)
    window.addEventListener('storage', refreshQuote)
    return () => {
      window.removeEventListener('notebuddy-settings-changed', refreshQuote)
      window.removeEventListener('storage', refreshQuote)
    }
  }, [])
  useEffect(() => {
    if (!createOpen) return
    const closeOutside = (event: PointerEvent) => {
      if (!createAreaRef.current?.contains(event.target as Node)) setCreateOpen(false)
    }
    const closeEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setCreateOpen(false) }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeEscape)
    }
  }, [createOpen])

  return (
    <aside className={`app-sidebar${isHome ? ' app-sidebar-home' : ''}`}>
      <div className="sidebar-header">
        <button className="brand-lockup" onClick={() => onNavigate('home')} aria-label="返回首页" title={collapsed ? '返回首页' : undefined}>
          <span className="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.7 3.8c-7 .3-12.4 2.4-14.6 6.8-1.5 3 .1 6.1 3.2 6.4 4.9.5 9.1-4.7 11.4-13.2Z"/><path d="M4.6 21c1.9-5.4 5.3-8.9 10.4-11.8"/></svg></span>
          <span><strong>NoteBuddy</strong><small>课程学习空间</small></span>
        </button>
        <button className="sidebar-collapse-toggle" type="button" aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!collapsed} onClick={() => onCollapsedChange(!collapsed)}>
          <span aria-hidden="true">{collapsed ? '›' : '‹'}</span>
        </button>
      </div>

      <div className="sidebar-create-area" ref={createAreaRef}>
        <button className="sidebar-create-button" type="button" title={collapsed ? '新建' : undefined} aria-expanded={createOpen} aria-controls={createOpen ? 'sidebar-create-menu' : undefined} onClick={() => setCreateOpen((open) => !open)}>
          <span aria-hidden="true">＋</span><span className="sidebar-create-label">新建</span>
        </button>
        {createOpen && <div className="sidebar-create-menu" id="sidebar-create-menu" aria-label="新建内容">
          <button type="button" onClick={() => { setCreateOpen(false); onCreateCourse() }}>新建课程</button>
          <button type="button" onClick={() => { setCreateOpen(false); onCreateNote() }}>新建笔记</button>
        </div>}
      </div>
      <nav className="sidebar-nav" aria-label="主导航">
        {primaryNavItems.map((item) => (
          <button className={`sidebar-link ${activeNav === item.id ? 'sidebar-link-active' : ''}`} key={item.id}
            type="button" aria-current={activeNav === item.id ? 'page' : undefined}
            title={collapsed ? item.label : undefined} onClick={() => onNavigate(item.id)}>
            <span className="sidebar-link-icon" aria-hidden="true"><SidebarIcon id={item.id} fallback={item.icon} /></span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      {!collapsed && <p className="home-sidebar-quote">{quote}</p>}
      {isHome && !collapsed && <svg className="home-sidebar-doodle" viewBox="0 0 220 132" aria-hidden="true">
        <path d="M14 116c47-8 128-9 192 1" fill="none" stroke="#ded7c3" strokeWidth="3" strokeLinecap="round"/>
        <path d="M57 81c-4-17 3-28 13-36 5 13 3 24-5 34m13 2c0-20 9-32 22-39 2 16-4 29-16 40m-39-2c-10-12-10-24-5-36 13 7 19 17 17 31" fill="#86aa70" stroke="#6c965b" strokeWidth="2" strokeLinejoin="round"/>
        <path d="M45 82h48l-6 30H51z" fill="#d7bd92" stroke="#aa8f65" strokeWidth="2"/>
        <path d="M94 101h51v11H94zm7-14h50v11h-50zm8-14h45v11h-45" fill="#f4f2e7" stroke="#526f61" strokeWidth="2" strokeLinejoin="round"/>
        <path d="M149 95c10-11 24-8 31 1l15 1c5 0 9 5 8 10l-1 5h-37c-8 0-14-5-16-12Z" fill="#fffdf6" stroke="#34483d" strokeWidth="2.5" strokeLinejoin="round"/>
        <path d="M181 94c3-8 11-10 16-7l-3 10m-25 4h1m16 0h1m-10 4 4 2 4-2" fill="none" stroke="#34483d" strokeWidth="2" strokeLinecap="round"/>
        <path d="m186 89 2-7m-2 8 7-4" fill="none" stroke="#34483d" strokeWidth="2" strokeLinecap="round"/>
        <path d="m20 37 4-8m10 14 7-4" fill="none" stroke="#729768" strokeWidth="3" strokeLinecap="round"/>
      </svg>}
      <div className="sidebar-footer">
        {footerNavItems.map((item) => (
          <button className="sidebar-settings-button" key={item.id} type="button" onClick={() => onNavigate(item.id)} aria-label={`打开${item.label}`}>
            <span className="sidebar-settings-icon" aria-hidden="true">{item.icon}</span>
            <span className="sidebar-settings-label">{item.label}</span>
          </button>
        ))}
      </div>
    </aside>
  )
}
