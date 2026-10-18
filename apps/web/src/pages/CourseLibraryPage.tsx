import { useEffect, useMemo, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import { CourseContextMenu, DeleteCourseDialog, RenameCourseDialog, type ContextMenuState } from '../CourseContextMenu'

const DAY = 86_400_000

/** 后端存的是不带时区的 UTC；浏览器会把它当本地时间，这里补 Z 再比较。 */
function parseApiTime(value: string) {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
  return Date.parse(hasZone ? value : `${value}Z`)
}

/** 课程账页上的日期只说人话：刚刚 / 2 小时前 / 10/17。 */
function formatRelative(value: string | null | undefined) {
  if (!value) return '尚未打开'
  const time = parseApiTime(value)
  if (!Number.isFinite(time)) return '尚未打开'
  const diff = Math.max(0, Date.now() - time)
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < DAY) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)} 天前`
  return new Date(time).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatCreated(value: string) {
  const time = parseApiTime(value)
  if (!Number.isFinite(time)) return '日期未知'
  return new Date(time).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function courseInitial(name: string) {
  return Array.from(name.trim())[0] ?? '课'
}

/** 课程页右侧的田野速写：一本摊开的笔记 + 一枝树叶。纯装饰，不参与语义。 */
function CourseFieldSketch() {
  return (
    <svg className="course-index-sketch" viewBox="0 0 280 240" aria-hidden="true" focusable="false">
      <path d="M28 196c40-17 78-17 112 0 34-17 72-17 112 0" fill="none" stroke="#E5E7E2" strokeWidth="1" />
      <g transform="translate(48 78) rotate(-5)">
        <path d="M0 0h82v96H0z" fill="#FFFFFF" stroke="#2F5D45" strokeWidth="1.1" strokeLinejoin="round" />
        <path d="M82 0l26 11v96H82z" fill="#F5F7F3" stroke="#2F5D45" strokeWidth="1.1" strokeLinejoin="round" />
        <path d="M8 14h60M8 25h46M8 36h56M8 47h38" fill="none" stroke="#8FA98C" strokeLinecap="round" strokeWidth="1" opacity=".55" />
        <path d="M26 62h34M26 72h22" fill="none" stroke="#B2684A" strokeLinecap="round" strokeWidth="1.2" opacity=".72" />
        <path d="M64 0v-18h8v18" fill="#E6D5B4" stroke="#B2684A" strokeWidth="1" strokeLinejoin="round" />
      </g>
      <g fill="none" stroke="#2F5D45" strokeLinecap="round" strokeLinejoin="round">
        <path d="M198 174c-8-48 6-82 36-106" strokeWidth="1.2" />
        <path d="M218 106c-16-2-26-10-30-25 15-1 26 6 32 20" fill="#E7EEE2" strokeWidth="1.1" />
        <path d="M224 90c6-16 18-25 34-27-1 16-10 27-26 32" fill="#F1F4ED" strokeWidth="1.1" />
        <path d="M208 132c-15 0-25-7-31-20 14-3 25 2 33 15" fill="#E7EEE2" strokeWidth="1.1" />
        <path d="M207 156c9-14 21-20 36-18-4 15-14 23-30 24" fill="#F1F4ED" strokeWidth="1.1" />
      </g>
      <circle cx="236" cy="58" r="2.2" fill="#B2684A" />
      <circle cx="52" cy="62" r="1.8" fill="#8FA98C" />
    </svg>
  )
}

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

  // 侧边栏「新建」跳到本页并带上该 state，用来直接打开新建课程侧栏。
  useEffect(() => {
    const state = location.state as { openCreateCourse?: boolean } | null
    if (!state?.openCreateCourse) return
    setError(undefined)
    setDialogOpen(true)
    navigate('/courses', { replace: true, state: null })
  }, [location.state, navigate])

  useEffect(() => {
    if (!dialogOpen) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !creating) setDialogOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [dialogOpen, creating])

  /** 最近打开的课排在最前；没有打开记录时按创建时间倒序，而不是让列表随机跳。 */
  const orderedCourses = useMemo(() => {
    return [...courses].sort((a, b) => {
      const openedA = a.last_opened_at ? Date.parse(a.last_opened_at) : 0
      const openedB = b.last_opened_at ? Date.parse(b.last_opened_at) : 0
      if (openedA !== openedB) return openedB - openedA
      return Date.parse(b.created_at) - Date.parse(a.created_at)
    })
  }, [courses])

  const currentCourse = orderedCourses[0]

  function openCreateSheet() {
    setError(undefined)
    setDialogOpen(true)
  }

  /** 触屏没有右键：用行尾的「⋯」把同一份菜单放到按钮下方。 */
  function openCourseMenu(event: ReactMouseEvent<HTMLButtonElement>, course: { id: string; name: string }) {
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    setContextMenu({
      x: Math.max(8, Math.min(rect.right - 168, window.innerWidth - 176)),
      y: Math.min(rect.bottom + 6, window.innerHeight - 100),
      courseId: course.id,
      courseName: course.name,
    })
  }

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

  async function handleRenameCourse(nextName: string) {
    if (!courseAction || courseActionSaving) return
    setCourseActionSaving(true)
    setError(undefined)
    try {
      await api.renameCourse(courseAction.courseId, nextName)
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
    <section className="course-index page-enter" aria-labelledby="course-index-title">
      <header className="course-index-head">
        <div className="course-index-title">
          <span className="eyebrow">COURSE LIBRARY · 课程库</span>
          <h1 id="course-index-title">课程</h1>
          <p>资料、笔记和知识结构，各归其位。</p>
        </div>
        <div className="course-index-actions">
          <Link className="course-index-recycle" to="/recycle">回收站 <span aria-hidden="true">↗</span></Link>
          <button className="primary-button course-index-new" type="button" onClick={openCreateSheet}>
            <span aria-hidden="true">＋</span> 新建课程
          </button>
        </div>
      </header>

      <div className="course-index-rule" aria-hidden="true">
        <span>{courses.length ? `${courses.length} 门课程` : '课程索引'}</span>
        <span>LOCAL · 仅本机保存</span>
      </div>

      {error && !dialogOpen && <p className="course-index-error" role="alert">{error}</p>}

      {coursesLoading ? (
        <div className="course-ledger course-ledger-skeleton" role="status" aria-label="正在读取课程">
          {[0, 1].map((row) => (
            <div className="course-ledger-skeleton-row" key={row}>
              <span />
              <span />
              <span>
                <i />
                <i />
              </span>
              <span />
            </div>
          ))}
        </div>
      ) : orderedCourses.length ? (
        <div className="course-ledger" aria-label="全部课程">
          {orderedCourses.map((course, index) => {
            const isCurrent = course.id === currentCourse?.id
            const opened = Boolean(course.last_opened_at)
            return (
              <div className="course-ledger-entry" key={course.id}>
                <Link
                  className={`course-ledger-row${isCurrent ? ' course-ledger-row-current' : ''}`}
                  to={`/courses/${course.id}`}
                  onContextMenu={(event) => {
                    event.preventDefault()
                    setContextMenu({ x: event.clientX, y: event.clientY, courseId: course.id, courseName: course.name })
                  }}
                >
                  <span className="course-ledger-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                  <span className="course-ledger-initial" aria-hidden="true">{courseInitial(course.name)}</span>
                  <span className="course-ledger-copy">
                    <strong>{course.name}</strong>
                    <small>{course.description || '查看课程资料、学习笔记和知识结构。'}</small>
                    {isCurrent && (
                      <span className="course-ledger-continue">继续这门课 <span aria-hidden="true">→</span></span>
                    )}
                  </span>
                  <span className="course-ledger-date">
                    <small>最近打开</small>
                    <time dateTime={course.last_opened_at ?? undefined}>{formatRelative(course.last_opened_at)}</time>
                    <small className="course-ledger-created">创建于 {formatCreated(course.created_at)}</small>
                  </span>
                  <span className={`course-ledger-status${isCurrent ? ' is-current' : ''}`}>
                    <i aria-hidden="true" />
                    {isCurrent ? '在读' : opened ? '打开过' : '未开始'}
                  </span>
                  <span className="course-ledger-arrow" aria-hidden="true">→</span>
                  <span className="course-ledger-spacer" aria-hidden="true" />
                </Link>
                <button
                  className="course-ledger-menu"
                  type="button"
                  aria-label={`打开${course.name}的更多操作`}
                  aria-haspopup="menu"
                  aria-expanded={contextMenu?.courseId === course.id}
                  title="更多操作"
                  onClick={(event) => openCourseMenu(event, course)}
                >⋯</button>
              </div>
            )
          })}
          <button className="course-ledger-new" type="button" onClick={openCreateSheet}>
            <span className="course-ledger-new-mark" aria-hidden="true">＋</span>
            <span className="course-ledger-new-copy"><strong>新建一门课程</strong><small>资料、笔记和知识结构，从这里开始。</small></span>
            <span className="course-ledger-new-arrow" aria-hidden="true">→</span>
          </button>
        </div>
      ) : (
        <div className="course-index-empty">
          <div className="course-index-empty-copy">
            <span className="eyebrow">FIRST FIELD NOTE</span>
            <h2>还没有课程。<br />先写下第一门课的名字。</h2>
            <p>资料、笔记和知识结构都会归入这门课；之后可以慢慢长成一片森林。</p>
            <div className="course-index-empty-actions">
              <button className="primary-button" type="button" onClick={openCreateSheet}>＋ 新建第一门课程</button>
              <Link className="course-index-recycle" to="/recycle">回收站里可以恢复已删除课程</Link>
            </div>
          </div>
          <CourseFieldSketch />
        </div>
      )}

      {!coursesLoading && orderedCourses.length > 0 && (
        <footer className="course-index-foot">
          <span>行尾 ⋯ 或右键课程，可重命名或移入回收站。</span>
          <span>课程会随资料与笔记慢慢长起来。</span>
        </footer>
      )}

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

      {dialogOpen && (
        <div
          className="course-sheet-backdrop"
          role="presentation"
          onMouseDown={(event) => { if (event.target === event.currentTarget && !creating) setDialogOpen(false) }}
        >
          <section
            className="course-create-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="course-create-title"
          >
            <header className="course-create-sheet-head">
              <span className="eyebrow">NEW FIELD NOTE</span>
              <button className="course-create-close" type="button" onClick={() => setDialogOpen(false)} disabled={creating} aria-label="关闭新建课程">×</button>
            </header>
            <h2 id="course-create-title">给这门课<br />起个名字。</h2>
            <p className="course-create-intro">它会是资料、笔记和知识结构的归处。名字之后可以改。</p>
            <form className="course-create-form" onSubmit={(event) => void handleCreateCourse(event)}>
              <label htmlFor="course-create-name">课程名称</label>
              <input
                id="course-create-name"
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：软件工程"
                maxLength={120}
              />
              <div className="course-create-suggestions" aria-label="课程名称示例">
                {['软件工程', '数据结构', '现代文学'].map((example) => (
                  <button key={example} type="button" onClick={() => setName(example)}>{example}</button>
                ))}
              </div>
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="primary-button course-create-submit" type="submit" disabled={!name.trim() || creating}>
                {creating ? '正在创建…' : '创建并打开'} <span aria-hidden="true">→</span>
              </button>
            </form>
            <p className="course-create-footnote"><span aria-hidden="true">●</span> 课程只保存在这台电脑上，不需要账号。</p>
          </section>
        </div>
      )}
    </section>
  )
}
