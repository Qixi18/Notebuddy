import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api'
import type { Course } from '../types'
import type { DeletedNotebookSummary } from '../api/courses'

export function RecycleBinPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [restoringId, setRestoringId] = useState<string>()
  const [notebooks, setNotebooks] = useState<DeletedNotebookSummary[]>([])

  async function load() {
    setLoading(true)
    setError(undefined)
    try {
      setCourses(await api.listDeletedCourses())
      setNotebooks(await api.listDeletedNotebooks())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '回收站读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  async function handleRestore(course: Course) {
    if (restoringId) return
    setRestoringId(course.id)
    setError(undefined)
    try {
      await api.restoreCourse(course.id)
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '课程恢复失败')
    } finally {
      setRestoringId(undefined)
    }
  }

  async function handleRestoreNotebook(notebook: DeletedNotebookSummary) {
    if (restoringId) return
    setRestoringId(notebook.id); setError(undefined)
    try { await api.restoreDeletedNotebook(notebook.id, notebook.course_id); await load() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '笔记恢复失败') }
    finally { setRestoringId(undefined) }
  }

  return (
    <section className="course-library page-enter" aria-labelledby="recycle-title">
      <header className="course-library-heading">
        <div>
          <h1 id="recycle-title">回收站</h1>
          <p>移入回收站的课程和笔记会保留内容与关联资料，可随时恢复。</p>
        </div>
        <Link className="secondary-button link-button" to="/courses">返回课程</Link>
      </header>

      {error && <p className="form-error" role="alert">{error}</p>}

      {loading ? <p className="course-library-state" role="status">正在读取回收站…</p> : courses.length ? (
        <section className="deleted-course-list" aria-label="已删除课程">
          {courses.map((course) => (
            <div className="deleted-course-row" key={course.id}>
              <span>{course.name}</span>
              <button className="ghost-button" type="button" disabled={Boolean(restoringId)} onClick={() => void handleRestore(course)}>
                {restoringId === course.id ? '正在恢复…' : '恢复'}
              </button>
            </div>
          ))}
        </section>
      ) : courses.length === 0 && notebooks.length === 0 ? (
        <div className="course-library-empty">
          <span aria-hidden="true">⌫</span>
          <strong>回收站是空的</strong>
          <p>在课程页移除课程后，它会出现在这里。</p>
        </div>
      ) : null}
      {!loading && notebooks.length > 0 && <section className="deleted-course-list" aria-label="已删除笔记"><h2>已删除笔记</h2>{notebooks.map((notebook) => <div className="deleted-course-row" key={notebook.id}><span>{notebook.title}</span><button className="ghost-button" type="button" disabled={Boolean(restoringId)} onClick={() => void handleRestoreNotebook(notebook)}>{restoringId === notebook.id ? '正在恢复…' : notebook.course_id ? '恢复到课程' : '恢复到未分类'}</button></div>)}</section>}
    </section>
  )
}
