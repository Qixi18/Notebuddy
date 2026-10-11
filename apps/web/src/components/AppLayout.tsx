import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
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
import { CourseSwitcher } from './CourseSwitcher'
import type { TeacherCharacterId } from './TeacherCharacter'
import { SettingsPanel } from '../SettingsPanel'
import { shouldBlockNoteNavigation } from '../features/notebook/navigation'

export type Feature = 'notes' | 'materials' | 'assistant'

export type WorkspaceContextValue = {
  courses: Course[]
  courseId?: string
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
  const { courseId, course, courses, coursesLoading, error, setError, noteDirty, setEditingNote } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const isHome = location.pathname === '/'
  const isForest = location.pathname === '/forest'
  const isAssistantPage = location.pathname.endsWith('/assistant')
  const showAssistantDock = !isHome && !isAssistantPage && !isForest
  const activeFeature = location.pathname.split('/')[3] as Feature | undefined
  const isCoursesPage = location.pathname === '/courses' || /^\/courses\/[^/]+$/.test(location.pathname)
  const isNotesLibrary = location.pathname === '/notes' || location.pathname.startsWith('/courses/') && (location.pathname.includes('/notes/') || location.pathname.endsWith('/notebook'))
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('notebuddy.sidebar-collapsed') === 'true')
  const [settingsOpen, setSettingsOpen] = useState(false)
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

  function openFeature(feature: Feature) {
    if (feature === 'notes') {
      navigate('/notes')
      return
    }
    if (courseId) {
      navigate(featurePath(courseId, feature))
    } else {
      navigate('/', { state: { pendingFeature: feature } })
    }
  }

  return (
    <div className={`app-shell${isHome ? ' app-shell-home' : isForest ? ' app-shell-forest' : showAssistantDock ? ' app-shell-with-assistant' : ''}${sidebarCollapsed ? ' app-shell-sidebar-collapsed' : ''}`}>
      <aside className={`app-sidebar${isHome ? ' app-sidebar-home' : ''}`}>
        <button className="brand-lockup" onClick={() => navigate('/')} aria-label="返回首页">
          <span className="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.7 3.8c-7 .3-12.4 2.4-14.6 6.8-1.5 3 .1 6.1 3.2 6.4 4.9.5 9.1-4.7 11.4-13.2Z"/><path d="M4.6 21c1.9-5.4 5.3-8.9 10.4-11.8"/></svg></span>
          <span><strong>NoteBuddy</strong><small>课程学习空间</small></span>
        </button>

        <button className="sidebar-collapse-toggle" type="button" aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!sidebarCollapsed} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}>
          <span aria-hidden="true">{sidebarCollapsed ? '›' : '‹'}</span><span className="sidebar-collapse-label">{sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}</span>
        </button>

        <div className="sidebar-section-label">学习空间</div>
        <button className={`sidebar-link ${location.pathname === '/' ? 'sidebar-link-active' : ''}`} onClick={() => navigate('/')}>
          <span className="sidebar-link-icon" aria-hidden="true">⌂</span><span>首页</span>
        </button>
        <button className={`sidebar-link ${isCoursesPage ? 'sidebar-link-active' : ''}`} onClick={() => navigate('/courses')}>
          <span className="sidebar-link-icon" aria-hidden="true">⌂</span><span>课程</span>
        </button>
        <button className={`sidebar-link ${isForest ? 'sidebar-link-active' : ''}`} onClick={() => navigate('/forest')} title={sidebarCollapsed ? '知识森林' : undefined}>
          <span className="sidebar-link-icon" aria-hidden="true">❧</span><span>知识森林</span>
        </button>
        {(Object.keys(featureLabels) as Feature[]).map((feature) => (
          <button
            className={`sidebar-link ${((feature === 'notes' && isNotesLibrary) || (feature !== 'notes' && activeFeature === feature)) ? 'sidebar-link-active' : ''}`}
            key={feature}
            onClick={() => openFeature(feature)}
            title={sidebarCollapsed ? featureLabels[feature] : undefined}
          >
            <span className="sidebar-link-icon" aria-hidden="true">
              {feature === 'notes' ? '▤' : feature === 'materials' ? '▱' : '✧'}
            </span>
            <span>{featureLabels[feature]}</span>
          </button>
        ))}

        {!isHome && !isNotesLibrary && !isCoursesPage && !isForest && <CourseSwitcher
          course={course}
          courses={courses}
          loading={coursesLoading}
          onSelect={(nextCourseId) => {
            const feature = activeFeature && featureLabels[activeFeature] ? activeFeature : undefined
            navigate(feature ? featurePath(nextCourseId, feature) : `/courses/${nextCourseId}`)
          }}
        />}

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
          <button className="sidebar-settings-button" type="button" onClick={() => setSettingsOpen(true)} aria-label="打开设置">⚙ 设置</button>
          <span className="local-status-dot" />本地学习空间 · 数据保存在本机
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
      {showAssistantDock && <AssistantDock />}
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
