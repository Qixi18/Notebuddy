import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { featureLabels, featurePath, useWorkspace, type Feature } from './AppLayout'
import { Dialog } from './Dialog'

export function CourseRouteGuard({ children }: { children: ReactNode }) {
  const { course, coursesLoading, refreshCourses } = useWorkspace()
  if (coursesLoading) return <div className="page-loading">正在读取课程…</div>
  if (!course) {
    return (
      <section className="route-state-card" role="alert">
        <span className="route-state-symbol">?</span>
        <h1>找不到这门课程</h1>
        <p>课程可能已被移除，或链接中的课程编号无效。</p>
        <Link className="primary-button link-button" to="/">返回首页选择课程</Link>
        <button className="text-button" onClick={() => void refreshCourses()}>重新读取课程</button>
      </section>
    )
  }
  return children
}

export function CourseGate({
  feature,
  onClose,
}: {
  feature: Feature
  onClose: () => void
}) {
  const { courses, createCourse, busy } = useWorkspace()
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string>()
  const navigate = useNavigate()

  async function openCourse(courseId: string) {
    navigate(featurePath(courseId, feature))
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName || submitting) return
    try {
      setSubmitting(true)
      setLocalError(undefined)
      const course = await createCourse(trimmedName)
      navigate(featurePath(course.id, feature))
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : '课程创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog title={`选择课程后打开${featureLabels[feature]}`} description="课程是笔记和学习资料的归属。选择后，继续这门课程的学习。" onClose={onClose} busy={submitting}>

        {courses.length > 0 && (
          <div className="course-gate-list" aria-label="已有课程">
            {courses.map((course) => (
              <button type="button" key={course.id} className="course-choice" disabled={submitting} onClick={() => void openCourse(course.id)}>
                <span className="course-choice-mark">{course.name.slice(0, 1)}</span>
                <span><strong>{course.name}</strong><small>打开{featureLabels[feature]}</small></span>
                <span className="course-choice-arrow" aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        )}

        <form className="course-gate-create botanical-dialog-form" onSubmit={handleCreate}>
          <label htmlFor="new-course-name">或者新建课程</label>
            <input
              id="new-course-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：软件工程"
              maxLength={120}
              autoFocus
              required
              disabled={submitting}
            />
          {localError && <p className="form-error" role="alert">{localError}</p>}
          <div className="botanical-dialog-actions">
            <button className="secondary-button" type="button" onClick={onClose} disabled={submitting}>取消</button>
            <button className="primary-button" type="submit" disabled={!name.trim() || submitting || busy}>
              {submitting ? '创建中…' : '创建并继续'}
            </button>
          </div>
        </form>
    </Dialog>
  )
}
