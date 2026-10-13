import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import { CourseContextMenu, DeleteCourseDialog, RenameCourseDialog, type ContextMenuState } from '../CourseContextMenu'

export function CourseLibraryPage() {
  const { courses, coursesLoading, createCourse, refreshCourses } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>()
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null)
  const [courseAction, setCourseAction] = useState<{ kind: 'rename' | 'delete'; courseId: string; courseName: string }>()
  const [courseActionSaving, setCourseActionSaving] = useState(false)

  // 侧边栏「新建」跳到本页并带上该 state，用来直接打开新建课程弹窗。
  useEffect(() => {
    const state = location.state as { openCreateCourse?: boolean } | null
    if (!state?.openCreateCourse) return
    setError(undefined)
    setDialogOpen(true)
    navigate('/courses', { replace: true, state: null })
  }, [location.state, navigate])

  async function handleCreateCourse(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || creating) return
    setCreating(true)
    setError(undefined)
    try {
      const course = await createCourse(name.trim())
      setDialogOpen(false)
      setName('')
      navigate(`/courses/${course.id}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程创建失败，请重试。')
    } finally {
      setCreating(false)
    }
  }

  async function handleRenameCourse(name: string) {
    if (!courseAction || courseActionSaving) return
    setCourseActionSaving(true)
    setError(undefined)
    try {
      await api.renameCourse(courseAction.courseId, name)
      await refreshCourses()
      setCourseAction(undefined)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程重命名失败')
    } finally { setCourseActionSaving(false) }
  }

  async function handleDeleteCourse() {
    if (!courseAction || courseActionSaving) return
    setCourseActionSaving(true)
    setError(undefined)
    try {
      await api.deleteCourse(courseAction.courseId)
      await refreshCourses()
      setCourseAction(undefined)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程移入回收站失败')
    } finally { setCourseActionSaving(false) }
  }

  return (
    <section className="course-library page-enter" aria-labelledby="course-library-title">
      <header className="course-library-heading">
        <div><h1 id="course-library-title">课程</h1><p>按课程整理资料、笔记与知识结构。</p></div>
        <div className="course-library-heading-actions">
          <Link className="secondary-button link-button" to="/recycle">回收站</Link>
          <button className="primary-button" type="button" onClick={() => { setError(undefined); setDialogOpen(true) }}>＋ 新建课程</button>
        </div>
      </header>

      {coursesLoading ? <p className="course-library-state" role="status">正在读取课程…</p> : courses.length ? (
        <div className="course-library-grid" aria-label="全部课程">
          {courses.map((course, index) => (
            <Link className={`course-library-card course-library-card-${index % 3}`} key={course.id} to={`/courses/${course.id}`} onContextMenu={(event) => { event.preventDefault(); setContextMenu({ x: event.clientX, y: event.clientY, courseId: course.id, courseName: course.name }) }}>
              <span className="course-library-card-mark" aria-hidden="true">{index % 3 === 0 ? '⌂' : index % 3 === 1 ? '✧' : '▤'}</span>
              <span className="course-library-card-copy"><strong>{course.name}</strong><small>{course.description || '查看课程资料、学习笔记和知识结构。'}</small><time dateTime={course.created_at}>创建于 {new Date(course.created_at).toLocaleDateString('zh-CN')}</time></span>
              <span className="course-library-card-arrow" aria-hidden="true">→</span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="course-library-empty"><span aria-hidden="true">⌂</span><strong>先创建一门课程</strong><p>资料、笔记和知识结构都会归入对应课程。</p><button className="secondary-button" type="button" onClick={() => setDialogOpen(true)}>＋ 新建课程</button></div>
      )}

      {error && <p className="form-error" role="alert">{error}</p>}

      <CourseContextMenu
        state={contextMenu}
        onClose={() => setContextMenu(null)}
        onRename={(courseId, courseName) => { setContextMenu(null); setCourseAction({ kind: 'rename', courseId, courseName }) }}
        onDelete={(courseId, courseName) => { setContextMenu(null); setCourseAction({ kind: 'delete', courseId, courseName }) }}
      />
      <RenameCourseDialog
        open={courseAction?.kind === 'rename'}
        initialName={courseAction?.courseName ?? ''}
        saving={courseActionSaving}
        onSubmit={(nextName) => void handleRenameCourse(nextName)}
        onCancel={() => setCourseAction(undefined)}
      />
      <DeleteCourseDialog
        open={courseAction?.kind === 'delete'}
        courseName={courseAction?.courseName ?? ''}
        saving={courseActionSaving}
        onConfirm={() => void handleDeleteCourse()}
        onCancel={() => setCourseAction(undefined)}
      />

      {dialogOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !creating) setDialogOpen(false) }}>
        <section className="course-gate-modal course-library-dialog" role="dialog" aria-modal="true" aria-labelledby="course-library-create-title">
          <button className="modal-close" type="button" onClick={() => setDialogOpen(false)} disabled={creating} aria-label="关闭">×</button>
          <span className="eyebrow">新的学习空间</span>
          <h2 id="course-library-create-title">新建课程</h2>
          <p className="muted-copy">课程资料、笔记和知识结构会分别保存在这个空间中。</p>
          <form className="home-create-course" onSubmit={(event) => void handleCreateCourse(event)}>
            <label htmlFor="course-library-name">课程名称</label>
            <div className="home-create-course-row"><input id="course-library-name" autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：软件工程" maxLength={120} /><button className="primary-button" type="submit" disabled={!name.trim() || creating}>{creating ? '正在创建…' : '创建并打开'}</button></div>
            {error && <p className="form-error" role="alert">{error}</p>}
          </form>
        </section>
      </div>}
    </section>
  )
}
