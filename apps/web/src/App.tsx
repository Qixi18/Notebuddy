import { Link, Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { lazy, Suspense, useEffect, useState } from 'react'

import { AppLayout, WorkspaceProvider } from './components/AppLayout'
import { CourseRouteGuard } from './components/CourseGate'
import { useWorkspaceState } from './features/workspace/useWorkspaceState'
import { api } from './api'
import { AssistantPage } from './pages/AssistantPage'
import { CourseOverviewPage } from './pages/CourseOverviewPage'
import { CourseLibraryPage } from './pages/CourseLibraryPage'
import { HomePage } from './pages/HomePage'
import { NotebookPage } from './pages/NotebookPage'
import { UnboundNotebookPage } from './pages/UnboundNotebookPage'
import { RecycleBinPage } from './pages/RecycleBinPage'

const ForestPage = lazy(() => import('./pages/ForestPage').then((module) => ({ default: module.ForestPage })))

export function LegacyMaterialsRedirect() {
  const { courseId } = useParams<{ courseId: string }>()
  const location = useLocation()
  const requestedNotebook = new URLSearchParams(location.search).get('notebook')
  const [target, setTarget] = useState<string>()
  useEffect(() => {
    if (!courseId) { setTarget('/courses'); return }
    let active = true
    void api.listNotebooks(courseId).then((notebooks) => {
      if (!active) return
      const notebook = requestedNotebook
        ? notebooks.find((item) => item.id === requestedNotebook)
        : notebooks[0]
      setTarget(notebook ? `/courses/${courseId}/notebooks/${notebook.id}` : `/courses/${courseId}`)
    }).catch(() => { if (active) setTarget(`/courses/${courseId}`) })
    return () => { active = false }
  }, [courseId, requestedNotebook])
  return target ? <Navigate to={target} replace /> : <p role="status">正在打开课程笔记本…</p>
}

function NotFoundPage() {
  return (
    <section className="route-state-card">
      <span className="route-state-symbol">404</span>
      <h1>没有找到这个页面</h1>
      <p>请从首页选择课程和功能。</p>
      <Link className="primary-button link-button" to="/">返回首页</Link>
    </section>
  )
}

function App() {
  const workspace = useWorkspaceState()

  return (
    <WorkspaceProvider value={workspace}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="/courses" element={<CourseLibraryPage />} />
          <Route path="/notebooks/unbound/:notebookId" element={<UnboundNotebookPage />} />
          <Route path="/recycle" element={<RecycleBinPage />} />
          <Route path="/forest" element={<Suspense fallback={<p role="status">正在打开知识森林…</p>}><ForestPage /></Suspense>} />
          <Route path="/courses/:courseId" element={<CourseRouteGuard><CourseOverviewPage /></CourseRouteGuard>} />
          <Route path="/notes" element={<Navigate to="/courses" replace />} />
          <Route path="/courses/:courseId/notebook" element={<Navigate to="/courses" replace />} />
          <Route path="/courses/:courseId/notebooks/:notebookId" element={<CourseRouteGuard><NotebookPage /></CourseRouteGuard>} />
          <Route path="/courses/:courseId/notes" element={<Navigate to="/courses" replace />} />
          <Route path="/courses/:courseId/notes/:noteId" element={<Navigate to="/courses" replace />} />
          <Route path="/courses/:courseId/materials" element={<CourseRouteGuard><LegacyMaterialsRedirect /></CourseRouteGuard>} />
          <Route path="/courses/:courseId/assistant" element={<CourseRouteGuard><AssistantPage /></CourseRouteGuard>} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  )
}

export default App
