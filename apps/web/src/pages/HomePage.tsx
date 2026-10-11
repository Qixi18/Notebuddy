import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { CourseGate } from '../components/CourseGate'
import {
  featurePath,
  type Feature,
  useWorkspace,
} from '../components/AppLayout'
import { TeacherCharacter } from '../components/TeacherCharacter'
import { cycleTeacherCharacter, useTeacherCharacter } from '../features/persona/useTeacherCharacter'
import { api } from '../api'
import type { Course, Material, Note } from '../types'

export function HomePage() {
  const { courses, coursesLoading, createCourse, busy } = useWorkspace()
  const [requestedFeature, setRequestedFeature] = useState<Feature>()
  const [newCourseName, setNewCourseName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string>()
  const [attentionMaterials, setAttentionMaterials] = useState<Material[]>([])
  const [materialCounts, setMaterialCounts] = useState<Record<string, number>>({})
  const [recentNotes, setRecentNotes] = useState<Array<{ note: Note; course: Course }>>([])
  const [homeQuestion, setHomeQuestion] = useState('')
  const [questionCourseId, setQuestionCourseId] = useState('')
  const [showCreateCourseDialog, setShowCreateCourseDialog] = useState(false)
  const [teacherCharacter] = useTeacherCharacter()
  const location = useLocation()
  const navigate = useNavigate()
  const isModalOpen = showCreateCourseDialog

  useEffect(() => {
    if (!isModalOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previousOverflow }
  }, [isModalOpen])

  useEffect(() => {
    if (!isModalOpen) return
    function handleModalKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      if (showCreateCourseDialog && !creating) setShowCreateCourseDialog(false)
    }
    window.addEventListener('keydown', handleModalKeyDown)
    return () => window.removeEventListener('keydown', handleModalKeyDown)
  }, [isModalOpen, showCreateCourseDialog, creating])

  function openCreateCourse() {
    setNewCourseName('')
    setCreateError(undefined)
    setShowCreateCourseDialog(true)
  }

  useEffect(() => {
    let active = true
    if (!courses.length) { setAttentionMaterials([]); return () => { active = false } }
    void Promise.all(courses.map((course) => api.listMaterials(course.id)))
      .then((collections) => { if (active) {
        setMaterialCounts(Object.fromEntries(courses.map((course, index) => [course.id, collections[index].length])))
        setAttentionMaterials(collections.flat().filter((material) => material.status === 'pending' || material.status === 'processing' || material.status === 'failed').slice(0, 4))
      } })
      .catch(() => { if (active) setAttentionMaterials([]) })
    return () => { active = false }
  }, [courses])

  useEffect(() => {
    let active = true
    if (!courses.length) { setRecentNotes([]); return () => { active = false } }
    void Promise.all(courses.map(async (course) => (await api.listNotes(course.id)).map((note) => ({ note, course }))))
      .then((collections) => {
        if (!active) return
        setRecentNotes(collections.flat().sort((left, right) => right.note.updated_at.localeCompare(left.note.updated_at)).slice(0, 3))
      })
      .catch(() => { if (active) setRecentNotes([]) })
    return () => { active = false }
  }, [courses])

  useEffect(() => {
    const state = location.state as { pendingFeature?: Feature; openCreateCourse?: boolean } | null
    if (state?.pendingFeature) {
      setRequestedFeature(state.pendingFeature)
      navigate('/', { replace: true, state: null })
      return
    }
    if (state?.openCreateCourse) {
      openCreateCourse()
      navigate('/', { replace: true, state: null })
    }
  }, [location.state, navigate])

  async function handleCreateCourse(event: FormEvent) {
    event.preventDefault()
    if (!newCourseName.trim() || creating) return
    try {
      setCreating(true)
      setCreateError(undefined)
      const course = await createCourse(newCourseName.trim())
      setShowCreateCourseDialog(false)
      navigate(`/courses/${course.id}`)
    } catch (cause) {
      setCreateError(cause instanceof Error ? cause.message : '课程创建失败')
    } finally {
      setCreating(false)
    }
  }

  const questionCourse = courses.find((course) => course.id === questionCourseId) ?? getMostRecentlyVisitedCourse(courses)

  function handleQuestionSubmit(event: FormEvent) {
    event.preventDefault()
    if (!questionCourse || !homeQuestion.trim()) return
    const initialQuestion = homeQuestion.trim()
    setHomeQuestion('')
    navigate(featurePath(questionCourse.id, 'assistant'), { state: { initialQuestion } })
  }

  function openCourseMaterials() {
    if (!questionCourse) {
      setRequestedFeature('materials')
      return
    }
    navigate(featurePath(questionCourse.id, 'materials'))
  }

  return (
    <div className="home-page home-screen-v2 page-enter">
      <div className="home-center-column">
        <header className="home-welcome" aria-labelledby="welcome-title">
          <h1 id="welcome-title">你好，今天想学点什么？</h1>
          <span className="home-welcome-spark" aria-hidden="true">✦</span>
        </header>

        <form className="home-question-composer" onSubmit={handleQuestionSubmit}>
          <textarea
            aria-label="课程问题"
            value={homeQuestion}
            onChange={(event) => setHomeQuestion(event.target.value)}
            placeholder={questionCourse ? `问问「${questionCourse.name}」里的内容…` : '先创建或选择一门课程，再提问…'}
            rows={3}
          />
          <div className="home-composer-toolbar">
            <div className="home-composer-tools">
              <button type="button" aria-label="打开课程资料上传课件" title="打开课程资料上传课件" onClick={openCourseMaterials}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.7 12.9 14.8 6.8a3.2 3.2 0 0 1 4.5 4.5l-8.1 8.1a5 5 0 0 1-7.1-7.1l8.2-8.2"/><path d="m7.3 14.3 7.1-7.1"/></svg>
              </button>
              <button type="button" aria-label="查看课程资料" title="查看课程资料" onClick={openCourseMaterials}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><circle cx="9" cy="9" r="1.5"/><path d="m5 17 5-5 3.2 3.2 2.2-2.2 3.6 4"/></svg>
              </button>
              {courses.length > 1 ? (
                <select aria-label="提问课程" value={questionCourse?.id ?? ''} onChange={(event) => setQuestionCourseId(event.target.value)}>
                  <option value="" disabled>选择课程</option>
                  {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
                </select>
              ) : questionCourse ? <span className="home-question-course">{questionCourse.name}</span> : null}
            </div>
            <button className="home-question-send" type="submit" disabled={!questionCourse || !homeQuestion.trim()}>
              发送 <span aria-hidden="true">➤</span>
            </button>
          </div>
        </form>

        <div className="home-lower-grid">
          <section className="home-content-panel home-recent-panel" aria-labelledby="recent-notes-title">
            <header className="home-panel-heading">
              <h2 id="recent-notes-title"><span aria-hidden="true">▤</span>最近笔记</h2>
              {recentNotes.length > 0 && <button type="button" onClick={() => navigate('/notes')} aria-label="打开全部笔记">···</button>}
            </header>
            {coursesLoading ? <p className="home-panel-empty">正在读取笔记…</p> : recentNotes.length ? (
              <div className="home-recent-list">
                {recentNotes.map(({ note, course }, index) => (
                  <button className="home-recent-note" key={note.id} onClick={() => navigate(`/courses/${course.id}/notes/${note.id}`)}>
                    <span className={`home-recent-note-icon home-recent-note-icon-${index}`} aria-hidden="true">{index === 0 ? '文' : index === 1 ? '记' : '知'}</span>
                    <span className="home-recent-note-copy"><strong>{note.title}</strong><small>{course.name} · {formatShortDate(note.updated_at)}</small></span>
                    <span className="home-recent-note-arrow" aria-hidden="true">···</span>
                  </button>
                ))}
              </div>
            ) : <p className="home-panel-empty">课程笔记会显示在这里。</p>}
          </section>

          <section className="home-content-panel home-learning-panel" id="home-current-course" aria-labelledby="current-course-title">
            <header className="home-panel-heading">
              <h2 id="current-course-title"><span aria-hidden="true">⌂</span>正在学习</h2>
              <button type="button" onClick={openCreateCourse} aria-label="新建课程">＋</button>
            </header>
            {coursesLoading ? <p className="home-panel-empty">正在读取课程…</p> : questionCourse ? (
              <>
                <button className="home-learning-course" onClick={() => navigate(`/courses/${questionCourse.id}`)}>
                  <span className="home-learning-illustration" aria-hidden="true">
                    <svg viewBox="0 0 112 104"><rect x="12" y="22" width="68" height="52" rx="5"/><path d="M5 82h83M35 74v8m23-8v8M32 43l-9 9 9 9m20-18 9 9-9 9m-3-15-8 13"/><path d="M83 62h23v7H83zm-4 11h27v7H79z"/></svg>
                  </span>
                  <span className="home-learning-course-copy"><strong>{questionCourse.name}</strong><small>{materialCounts[questionCourse.id] ?? 0} 份课程资料 · {getLastVisited(questionCourse.id) ? `最近学习 ${formatShortDate(getLastVisited(questionCourse.id)!)}` : '开始你的课程学习'}</small></span>
                  <span className="home-learning-arrow" aria-hidden="true">→</span>
                </button>
                {courses.length > 1 && <label className="home-switch-course">切换课程<select aria-label="切换正在学习的课程" value={questionCourse.id} onChange={(event) => setQuestionCourseId(event.target.value)}>{courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}</select></label>}
              </>
            ) : <div className="home-panel-empty home-no-course"><p>创建课程后，这里会显示你的学习进度。</p><button className="text-button" type="button" onClick={openCreateCourse}>＋ 创建课程</button></div>}
          </section>
        </div>

        {attentionMaterials.length > 0 && <details className="home-secondary-panel home-attention-disclosure"><summary>资料处理提醒 · {attentionMaterials.length}</summary><div className="home-attention-list">{attentionMaterials.map((material) => {
        const course = courses.find((item) => item.id === material.course_id)
        return <button className={`home-attention-item home-attention-${material.status}`} key={material.id} onClick={() => navigate(`/courses/${material.course_id}/materials`)}><span className="home-attention-mark">{material.status === 'failed' ? '!' : '·'}</span><span><strong>{course?.name} · {material.lecture_title}</strong><small>{material.status === 'failed' ? '解析失败，打开资料查看错误并重试。' : material.status === 'pending' ? '资料等待处理。' : '资料正在解析。'}</small></span><span aria-hidden="true">→</span></button>
      })}</div></details>}
      </div>

      <aside className="home-teacher-column" aria-label="AI 教师">
        <div className="home-teacher-frame">
          <button className="home-teacher-switch" type="button" onClick={cycleTeacherCharacter} title="切换教师形象" aria-label="切换教师形象">
            ⇄
          </button>
          <TeacherCharacter animated character={teacherCharacter} />
        </div>
      </aside>

      {requestedFeature && (
        <CourseGate feature={requestedFeature} onClose={() => setRequestedFeature(undefined)} />
      )}
      {showCreateCourseDialog && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !creating) setShowCreateCourseDialog(false) }}>
        <section className="course-gate-modal home-course-create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-course-title">
          <button className="modal-close" type="button" onClick={() => setShowCreateCourseDialog(false)} disabled={creating} aria-label="关闭">×</button>
          <span className="eyebrow">新的学习空间</span>
          <h2 id="create-course-title">创建课程</h2>
          <p className="muted-copy">课程资料、笔记和知识结构会分别保存在这个空间中。</p>
          <form className="home-create-course" onSubmit={handleCreateCourse}>
            <label htmlFor="home-course-name">课程名称</label>
            <div className="home-create-course-row">
              <input id="home-course-name" autoFocus value={newCourseName} onChange={(event) => setNewCourseName(event.target.value)} placeholder="例如：软件工程" maxLength={120} />
              <button className="primary-button" type="submit" disabled={!newCourseName.trim() || creating || busy}>{creating ? '正在创建…' : '创建并打开'}</button>
            </div>
            {createError && <p className="form-error" role="alert">{createError}</p>}
          </form>
        </section>
      </div>}
    </div>
  )
}

function getLastVisited(courseId: string): string | null {
  try { return localStorage.getItem(`notebuddy.course.${courseId}.lastVisited`) } catch { return null }
}

function getMostRecentlyVisitedCourse(courses: Course[]): Course | undefined {
  return [...courses].sort((left, right) => {
    const leftDate = getLastVisited(left.id) ?? left.created_at
    const rightDate = getLastVisited(right.id) ?? right.created_at
    return rightDate.localeCompare(leftDate)
  })[0]
}

function formatShortDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}
