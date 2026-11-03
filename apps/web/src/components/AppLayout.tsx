import { createContext, lazy, Suspense, useContext, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import type {
  Course,
  Job,
  KnowledgeGraph,
  Material,
  Page,
  UploadResponse,
} from '../types'
import type { ConversationState } from '../features/conversation/useConversation'
import { NotebookBridgeProvider } from '../features/notebook-editor/NotebookBridge'
import { SettingsPanel } from './SettingsPanel'
import { NotebookNavigationGuard } from '../features/notebook-workspace/NotebookNavigationGuard'
import { useAssistantDockController } from '../features/assistant/useAssistantDockController'
import { readStorage } from '../utils/safeStorage'
import type { SidebarNavId } from '../features/navigation/sidebarNav'
import { AppSidebar } from './AppSidebar'

const AssistantDock = lazy(() => import('../features/assistant/AssistantDock').then((module) => ({ default: module.AssistantDock })))

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
  graph: KnowledgeGraph
  job?: Job
  /** 答疑的唯一状态源：首页「问 AI」、答疑页、悬浮答疑坞共用同一份会话 */
  conversation: ConversationState
  busy: boolean
  documentDirty: boolean
  setDocumentDirty: (dirty: boolean) => void
  error?: string
  setError: (message: string | undefined) => void
  createCourse: (name: string) => Promise<Course>
  uploadMaterial: (file: File, lectureTitle: string, notebookId: string, topicTitle?: string, allowDuplicate?: boolean, batchId?: string, processingRoute?: 'standard' | 'llm') => Promise<UploadResponse>
  retryMaterial: (materialId: string) => Promise<void>
  reparseMaterial: (materialId: string) => Promise<void>
  requestOCR: (materialId: string) => Promise<void>
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
  if (feature === 'materials') return `/courses/${courseId}`
  return `/courses/${courseId}/${feature}`
}

export function AppLayout() {
  const { courseId, courses, error, setError, documentDirty, setDocumentDirty } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const isHome = location.pathname === '/'
  const isForest = location.pathname === '/forest'
  const isAssistantPage = location.pathname.endsWith('/assistant')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readStorage('notebuddy.sidebar-collapsed') === 'true')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const dock = useAssistantDockController()
  /* 答疑页本身就是完整助手，此处再挂一个紧凑抽屉纯属重复，故该页整页不提供悬浮球与抽屉；
     其余页面（含首页、知识森林）全局常驻 */
  const dockSupported = !isAssistantPage
  const showAssistantDock = dockSupported && dock.open

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
    <NotebookBridgeProvider>
    <div
      className={`app-shell app-shell-garden${isHome ? ' app-shell-home' : isForest ? ' app-shell-forest' : ''}${showAssistantDock ? ' app-shell-with-assistant' : ''}${sidebarCollapsed ? ' app-shell-sidebar-collapsed' : ''}${dock.resizing ? ' app-shell-dock-resizing' : ''}`}
      /* 抽屉宽度只在这一处写进 CSS 变量，网格第三列引用它，拖拽即改一格变量 */
      style={{ '--dock-w': `${dock.width}px` } as CSSProperties}
    >
      <AppSidebar isHome={isHome} collapsed={sidebarCollapsed} onCollapsedChange={setSidebarCollapsed}
        onNavigate={handleNav}
        onCreateCourse={() => navigate('/courses', { state: { openCreateCourse: true } })}
        onCreateNote={() => navigate('/courses', { state: { openCreateNote: true } })} />

      <main className={`app-main${isHome ? ' app-main-home' : isForest ? ' app-main-forest' : ''}`}>
        {error && (
          <div className="global-alert" role="alert">
            <span>{error}</span>
            <button onClick={() => setError(undefined)} aria-label="关闭提示">×</button>
          </div>
        )}
        <Outlet />
      </main>
      {showAssistantDock && <Suspense fallback={null}><AssistantDock
        width={dock.width}
        onWidthChange={dock.setWidth}
        onClose={() => dock.setOpen(false)}
        onResizeStateChange={dock.setResizing}
        notebookAction={dock.notebookAction}
        onNotebookActionConsumed={dock.clearNotebookAction}
      /></Suspense>}
      {dockSupported && !dock.open && <button
        className="assistant-fab"
        type="button"
        onClick={() => dock.setOpen(true)}
        aria-label="打开课程学习助手"
        title="打开课程学习助手"
      >
        <span className="assistant-fab-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" focusable="false">
            <path d="M3.5 12.2c2.8-3.8 7.3-4.8 11.5-2.4 1.1.6 2 1.5 2.6 2.6-.9.4-1.9.6-2.9.6-4 0-7.7-.3-11.2-.8Z" />
            <path d="M17.6 13.1c1.5-1.5 3-2.1 4.4-2-.5 1.5-1.3 2.7-2.5 3.7" />
            <circle cx="6.8" cy="11.6" r=".8" fill="currentColor" stroke="none" />
          </svg>
        </span>
        <span className="assistant-fab-label" aria-hidden="true">叫桌宠来</span>
      </button>}
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
      <NotebookNavigationGuard dirty={documentDirty} onDiscard={() => setDocumentDirty(false)} />
    </div>
    </NotebookBridgeProvider>
  )
}

export { featureLabels, featureDescriptions }
