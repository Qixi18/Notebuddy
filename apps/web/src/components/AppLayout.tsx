import { createContext, useContext, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Outlet, useBlocker, useLocation, useNavigate } from 'react-router-dom'

import type {
  Course,
  Job,
  KnowledgeGraph,
  Material,
  Note,
  Page,
} from '../types'
import type { ConversationState } from '../features/conversation/useConversation'
import { AssistantDock } from './AssistantDock'
import { ConfirmDialog } from './ConfirmDialog'
import type { TeacherCharacterId } from './TeacherCharacter'
import { SettingsPanel } from '../SettingsPanel'
import { shouldBlockNoteNavigation } from '../features/notebook/navigation'
import { footerNavItems, primaryNavItems, resolveActiveNav, type SidebarNavId } from '../features/navigation/sidebarNav'
import { DOCK_STORAGE, resolveDockOpen, resolveDockWidth } from '../features/assistant/dockLayout'

export type Feature = 'notes' | 'materials' | 'assistant'

export type WorkspaceContextValue = {
  courses: Course[]
  courseId?: string
  /** 会话挂靠的课程：URL 课程，或没有 URL 课程时退回的最近访问课程（悬浮坞据此提问） */
  conversationCourseId?: string
  course?: Course
  coursesLoading: boolean
  courseContentLoading: boolean
  materials: Material[]
  selectedMaterialId?: string
  setSelectedMaterialId: (id: string | undefined) => void
  pages: Page[]
  selectedPageNumber?: number
  setSelectedPageNumber: (page: number | undefined) => void
  openMaterialSource: (materialId: string, page: number | undefined) => void
  notes: Note[]
  upsertNotes: (notes: Note[]) => void
  selectedNote?: Note
  setSelectedNoteId: (id: string | undefined) => void
  noteDraft: string
  setNoteDraft: (value: string) => void
  editingNote: boolean
  setEditingNote: (editing: boolean) => void
  graph: KnowledgeGraph
  job?: Job
  /** 当前选中的 AI 教师，决定答疑回答的表达风格 */
  teacherPersona: TeacherCharacterId
  setTeacherPersona: (id: TeacherCharacterId) => void
  /** 答疑的唯一状态源：首页「问 AI」、答疑页、悬浮答疑坞共用同一份会话 */
  conversation: ConversationState
  busy: boolean
  noteSaving: boolean
  noteDirty: boolean
  reloadNote: () => Promise<void>
  error?: string
  setError: (message: string | undefined) => void
  createCourse: (name: string) => Promise<Course>
  uploadMaterial: (file: File, lectureTitle: string, topicTitle?: string, allowDuplicate?: boolean) => Promise<void>
  retryMaterial: (materialId: string) => Promise<void>
  reparseMaterial: (materialId: string) => Promise<void>
  requestOCR: (materialId: string) => Promise<void>
  saveNote: () => Promise<void>
  refreshCourses: () => Promise<void>
  refreshCurrentMaterials: () => Promise<void>
  refreshCurrentNotes: () => Promise<void>
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function WorkspaceProvider({
  value,
  children,
}: {
  value: WorkspaceContextValue
  children: ReactNode
}) {
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext)
  if (!value) throw new Error('useWorkspace must be used inside WorkspaceProvider')
  return value
}

const featureLabels: Record<Feature, string> = {
  notes: '笔记',
  materials: '课程资料',
  assistant: 'AI 答疑',
}

const featureDescriptions: Record<Feature, string> = {
  notes: '整理与编辑课程笔记',
  materials: '上传课件并检查解析结果',
  assistant: '基于当前课程资料提问',
}

export function featurePath(courseId: string, feature: Feature): string {
  if (feature === 'notes') return `/courses/${courseId}/notebook`
  return `/courses/${courseId}/${feature}`
}

export function AppLayout() {
  const { courseId, courses, error, setError, noteDirty, setEditingNote } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const isHome = location.pathname === '/'
  const isForest = location.pathname === '/forest'
  const isAssistantPage = location.pathname.endsWith('/assistant')
  const activeNav = resolveActiveNav(location.pathname)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('notebuddy.sidebar-collapsed') === 'true')
  const [settingsOpen, setSettingsOpen] = useState(false)
  /* 抽屉开合与宽度都由外壳持有：宽度要写进 CSS 变量驱动网格列，正文才能跟着让位 */
  const [dockOpen, setDockOpen] = useState(() => resolveDockOpen(localStorage.getItem(DOCK_STORAGE.open)))
  const [dockWidth, setDockWidth] = useState(() => resolveDockWidth(localStorage.getItem(DOCK_STORAGE.width)))
  const [dockResizing, setDockResizing] = useState(false)
  /* 答疑页本身就是完整助手，此处再挂一个紧凑抽屉纯属重复，故该页整页不提供悬浮球与抽屉；
     其余页面（含首页、知识森林）全局常驻 */
  const dockSupported = !isAssistantPage
  const showAssistantDock = dockSupported && dockOpen
  const blocker = useBlocker(({ currentLocation, nextLocation }) => shouldBlockNoteNavigation(noteDirty, currentLocation, nextLocation))

  useEffect(() => {
    if (!noteDirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [noteDirty])

  useEffect(() => {
    localStorage.setItem('notebuddy.sidebar-collapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    localStorage.setItem(DOCK_STORAGE.open, String(dockOpen))
  }, [dockOpen])

  useEffect(() => {
    localStorage.setItem(DOCK_STORAGE.width, String(dockWidth))
  }, [dockWidth])

  function handleNav(id: SidebarNavId) {
    switch (id) {
      case 'home': navigate('/'); return
      // 新建是命令而不是页面：跳课程页并让页面打开新建课程弹窗，不留在侧边栏高亮。
      case 'create': navigate('/courses', { state: { openCreateCourse: true } }); return
      case 'courses': navigate('/courses'); return
      case 'forest': navigate('/forest'); return
      case 'recycle': navigate('/recycle'); return
      case 'assistant': {
        const target = courseId ?? courses[0]?.id
        navigate(target ? featurePath(target, 'assistant') : '/courses')
        return
      }
      case 'settings': setSettingsOpen(true); return
    }
  }

  return (
    <div
      className={`app-shell${isHome ? ' app-shell-home' : isForest ? ' app-shell-forest' : ''}${showAssistantDock ? ' app-shell-with-assistant' : ''}${sidebarCollapsed ? ' app-shell-sidebar-collapsed' : ''}${dockResizing ? ' app-shell-dock-resizing' : ''}`}
      /* 抽屉宽度只在这一处写进 CSS 变量，网格第三列引用它，拖拽即改一格变量 */
      style={{ '--dock-w': `${dockWidth}px` } as CSSProperties}
    >
      <aside className={`app-sidebar${isHome ? ' app-sidebar-home' : ''}`}>
        <div className="sidebar-header">
          <button className="brand-lockup" onClick={() => navigate('/')} aria-label="返回首页">
            <span className="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.7 3.8c-7 .3-12.4 2.4-14.6 6.8-1.5 3 .1 6.1 3.2 6.4 4.9.5 9.1-4.7 11.4-13.2Z"/><path d="M4.6 21c1.9-5.4 5.3-8.9 10.4-11.8"/></svg></span>
            <span><strong>NoteBuddy</strong><small>课程学习空间</small></span>
          </button>

          {/* 收起按钮贴侧边栏右上角：方形、纯图标，不带文字（展开态靠 aria-label 说明） */}
          <button className="sidebar-collapse-toggle" type="button" aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!sidebarCollapsed} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}>
            <span aria-hidden="true">{sidebarCollapsed ? '›' : '‹'}</span>
          </button>
        </div>

        <div className="sidebar-section-label">学习空间</div>
        <nav className="sidebar-nav" aria-label="主导航">
          {primaryNavItems.map((item) => (
            <button
              className={`sidebar-link ${activeNav === item.id ? 'sidebar-link-active' : ''}`}
              key={item.id}
              type="button"
              aria-current={activeNav === item.id ? 'page' : undefined}
              title={sidebarCollapsed ? item.label : undefined}
              onClick={() => handleNav(item.id)}
            >
              <span className="sidebar-link-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {isHome && !sidebarCollapsed && <svg className="home-sidebar-doodle" viewBox="0 0 220 132" aria-hidden="true">
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
            <button className="sidebar-settings-button" key={item.id} type="button" onClick={() => handleNav(item.id)} aria-label={`打开${item.label}`}>
              <span className="sidebar-settings-icon" aria-hidden="true">{item.icon}</span>
              <span className="sidebar-settings-label">{item.label}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className={`app-main${isHome ? ' app-main-home' : isForest ? ' app-main-forest' : ''}`}>
        {error && (
          <div className="global-alert" role="alert">
            <span>{error}</span>
            <button onClick={() => setError(undefined)} aria-label="关闭提示">×</button>
          </div>
        )}
        <Outlet />
      </main>
      {showAssistantDock && <AssistantDock
        width={dockWidth}
        onWidthChange={setDockWidth}
        onClose={() => setDockOpen(false)}
        onResizeStateChange={setDockResizing}
      />}
      {dockSupported && !dockOpen && <button
        className="assistant-fab"
        type="button"
        onClick={() => setDockOpen(true)}
        aria-label="打开课程学习助手"
        title="打开课程学习助手"
      ><span aria-hidden="true">✦</span></button>}
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
      {blocker.state === 'blocked' && <ConfirmDialog
        eyebrow="未保存的笔记"
        title="离开正在编辑的笔记？"
        description="当前修改尚未保存。离开此页面会丢弃这份草稿，已保存的笔记正文不会改变。"
        confirmLabel="放弃草稿并离开"
        cancelLabel="继续编辑"
        tone="danger"
        onConfirm={() => { setEditingNote(false); blocker.proceed() }}
        onCancel={() => blocker.reset()}
      />}
    </div>
  )
}

export { featureLabels, featureDescriptions }
