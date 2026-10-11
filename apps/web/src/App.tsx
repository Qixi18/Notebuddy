import { Link, Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout, WorkspaceProvider } from './components/AppLayout'
import { CourseRouteGuard } from './components/CourseGate'
import { useWorkspaceState } from './features/workspace/useWorkspaceState'
import { AssistantPage } from './pages/AssistantPage'
import { CourseOverviewPage } from './pages/CourseOverviewPage'
import { CourseLibraryPage } from './pages/CourseLibraryPage'
import { HomePage } from './pages/HomePage'
import { NotesLibraryPage } from './pages/NotesLibraryPage'
import { MaterialsPage } from './pages/MaterialsPage'
import { NotesPage } from './pages/NotesPage'
import { NotebookPage } from './pages/NotebookPage'

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
          <Route path="/courses/:courseId" element={<CourseRouteGuard><CourseOverviewPage /></CourseRouteGuard>} />
          <Route path="/notes" element={<NotesLibraryPage />} />
          <Route path="/courses/:courseId/notebook" element={<CourseRouteGuard><NotebookPage /></CourseRouteGuard>} />
          <Route path="/courses/:courseId/notes" element={<Navigate to="/notes" replace />} />
          <Route path="/courses/:courseId/notes/:noteId" element={<CourseRouteGuard><NotesPage /></CourseRouteGuard>} />
          <Route path="/courses/:courseId/materials" element={<CourseRouteGuard><MaterialsPage /></CourseRouteGuard>} />
          <Route path="/courses/:courseId/assistant" element={<CourseRouteGuard><AssistantPage /></CourseRouteGuard>} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </WorkspaceProvider>
  )
}

export default App
