import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import type { Course, NotebookSummary } from '../types'
import './CourseLibraryPage.css'

type CourseNotes = { course: Course; notes: NotebookSummary[]; error?: string }

function NoteCover({ variant, courseName }: { variant: number; courseName: string }) {
  const kind = variant % 5
  const coverLabel = /数学|微积分|代数/.test(courseName) ? 'MATHEMATICS' : /物理|力学|光学/.test(courseName) ? 'PHYSICS' : 'COURSE NOTE'
  return (
    <span className={`course-note-cover course-note-cover-${kind}`} aria-hidden="true">
      <span className="course-note-cover-label">{coverLabel}</span>
      <svg viewBox="0 0 180 200" fill="none" focusable="false">
        {kind === 0 && <><path d="M24 158h132M42 173V42" stroke="#a1b5a0" strokeWidth="1.5" /><path d="M25 151c26-5 30-79 59-84 29-5 30 69 69 64" stroke="#2f5d45" strokeWidth="3" strokeLinecap="round" /><text x="141" y="58" fill="#2f5d45" fontFamily="serif" fontSize="28">∫</text></>}
        {kind === 1 && <><path d="M24 155h132" stroke="#c7bca9" strokeWidth="1.5" /><path d="M28 125c17 0 27-48 49-48 19 0 25 59 44 59 13 0 20-23 37-23" stroke="#b2684a" strokeWidth="3" strokeLinecap="round" /><circle cx="77" cy="77" r="4" fill="#b2684a" /><circle cx="121" cy="136" r="4" fill="#b2684a" /></>}
        {kind === 2 && <><path d="M24 158h132M42 173V42" stroke="#a3bab5" strokeWidth="1.5" /><path d="M43 148c26 0 30-70 57-70s32-17 54-17" stroke="#3d7265" strokeWidth="3" strokeLinecap="round" /><path d="M100 72v77" stroke="#3d7265" strokeWidth="1.5" strokeDasharray="5 5" /></>}
        {kind === 3 && <><path d="M24 119c27-31 53-31 80 0s53 31 80 0M24 132c27-31 53-31 80 0s53 31 80 0" stroke="#4a7b71" strokeWidth="2.5" /><text x="137" y="164" fill="#2f5d45" fontFamily="serif" fontSize="28">λ</text></>}
        {kind === 4 && <><path d="M24 143h132" stroke="#b5ab97" strokeWidth="2" /><path d="M43 143c10-63 84-63 94 0" stroke="#9f7755" strokeWidth="3" /><circle cx="43" cy="143" r="5" fill="#9f7755" /><circle cx="137" cy="143" r="5" fill="#9f7755" /></>}
      </svg>
    </span>
  )
}

export function CourseLibraryPage() {
  const { courses, coursesLoading, createCourse } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const [groups, setGroups] = useState<CourseNotes[]>([])
  const [notesLoading, setNotesLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [newNoteOpen, setNewNoteOpen] = useState(false)
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [newNoteName, setNewNoteName] = useState('')
  const [creatingNote, setCreatingNote] = useState(false)
  const [newNoteError, setNewNoteError] = useState<string>()
  const [courseDialogOpen, setCourseDialogOpen] = useState(false)
  const [courseName, setCourseName] = useState('')
  const [creatingCourse, setCreatingCourse] = useState(false)
  const [createError, setCreateError] = useState<string>()

  // 继续承接侧边栏已有的「新建课程」入口。
  useEffect(() => {
    const state = location.state as { openCreateCourse?: boolean } | null
    if (!state?.openCreateCourse) return
    setCreateError(undefined)
    setCourseDialogOpen(true)
    navigate('/courses', { replace: true, state: null })
  }, [location.state, navigate])

  useEffect(() => {
    if (coursesLoading) return
    let active = true
    setNotesLoading(true)
    void Promise.all(courses.map(async (course): Promise<CourseNotes> => {
      try { return { course, notes: await api.listNotebooks(course.id) } }
      catch (cause) { return { course, notes: [], error: cause instanceof Error ? cause.message : '笔记读取失败' } }
    })).then((result) => { if (active) setGroups(result) })
      .finally(() => { if (active) setNotesLoading(false) })
    return () => { active = false }
  }, [courses, coursesLoading])

  useEffect(() => {
    if (!newNoteOpen && !courseDialogOpen) return
    function onEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      if (!creatingNote) setNewNoteOpen(false)
      if (!creatingCourse) setCourseDialogOpen(false)
    }
    window.addEventListener('keydown', onEscape)
    return () => window.removeEventListener('keydown', onEscape)
  }, [newNoteOpen, courseDialogOpen, creatingCourse, creatingNote])

  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return groups.map(({ course, notes, error }) => ({
      course, error,
      notes: needle && !course.name.toLocaleLowerCase().includes(needle)
        ? notes.filter((note) => note.title.toLocaleLowerCase().includes(needle))
        : notes,
    })).filter(({ course, notes }) => !needle || course.name.toLocaleLowerCase().includes(needle) || notes.length > 0)
  }, [groups, query])

  function openNewNote() {
    if (!courses.length) { setCourseDialogOpen(true); return }
    setSelectedCourseId((current) => current || courses[0]?.id || '')
    setNewNoteError(undefined)
    setNewNoteOpen(true)
  }

  async function handleCreateNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedCourseId || !newNoteName.trim() || creatingNote) return
    setCreatingNote(true)
    setNewNoteError(undefined)
    try {
      const notebook = await api.createNotebook(selectedCourseId, newNoteName.trim())
      setNewNoteOpen(false)
      setNewNoteName('')
      navigate(`/courses/${selectedCourseId}/notebooks/${notebook.id}`)
    } catch (cause) {
      setNewNoteError(cause instanceof Error ? cause.message : '笔记创建失败，请重试。')
    } finally { setCreatingNote(false) }
  }

  async function handleCreateCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!courseName.trim() || creatingCourse) return
    setCreatingCourse(true)
    setCreateError(undefined)
    try {
      const course = await createCourse(courseName.trim())
      setCourseDialogOpen(false)
      setCourseName('')
      navigate(`/courses/${course.id}`)
    } catch (cause) {
      setCreateError(cause instanceof Error ? cause.message : '课程创建失败，请重试。')
    } finally { setCreatingCourse(false) }
  }

  return (
    <section className="course-notes-page page-enter" aria-label="按课程分组的笔记">
      <div className="course-notes-toolbar">
        <label className="course-notes-search">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="10.8" cy="10.8" r="7.1" /><path d="m16 16 5 5" /></svg>
          <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" aria-label="搜索笔记或课程" placeholder="搜索笔记或课程…" />
        </label>
        <button className="course-notes-new" type="button" onClick={openNewNote}><span aria-hidden="true">＋</span> 新建笔记</button>
      </div>

      {coursesLoading || notesLoading ? (
        <div className="course-notes-loading" role="status" aria-label="正在读取课程笔记">
          <span className="course-notes-loading-title" />
          <div className="course-notes-loading-grid">{[0, 1, 2].map((item) => <span key={item} />)}</div>
        </div>
      ) : courses.length === 0 ? (
        <div className="course-notes-empty"><h2>还没有课程</h2><p>先创建一门课程，再开始第一篇笔记。</p><button type="button" onClick={() => setCourseDialogOpen(true)}>新建课程</button></div>
      ) : visibleGroups.length === 0 ? (
        <div className="course-notes-empty"><h2>没有找到相关笔记</h2><p>试试其他笔记名称或课程名称。</p></div>
      ) : (
        <div className="course-notes-groups">
          {visibleGroups.map(({ course, notes, error }, groupIndex) => (
            <section className="course-notes-group" key={course.id} aria-labelledby={`course-notes-${course.id}`}>
              <div className="course-notes-group-heading">
                <h2 id={`course-notes-${course.id}`}>{course.name}</h2>
                <span>{notes.length} 篇笔记</span>
              </div>
              {error ? <p className="course-notes-error" role="alert">{course.name}的笔记读取失败：{error}</p> : notes.length ? (
                <div className="course-notes-grid">
                  {notes.map((note, noteIndex) => (
                    <Link className="course-note-card" key={note.id} to={`/courses/${course.id}/notebooks/${note.id}`} aria-label={`打开笔记：${note.title}`}>
                      <NoteCover variant={groupIndex * 3 + noteIndex} courseName={course.name} />
                      <strong>{note.title}</strong>
                    </Link>
                  ))}
                </div>
              ) : <p className="course-notes-group-empty">这门课程还没有笔记。</p>}
            </section>
          ))}
        </div>
      )}

      {newNoteOpen && (
        <div className="course-notes-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !creatingNote) setNewNoteOpen(false) }}>
          <section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-notes-new-title">
            <button className="course-notes-dialog-close" type="button" onClick={() => setNewNoteOpen(false)} disabled={creatingNote} aria-label="关闭">×</button>
            <h2 id="course-notes-new-title">新建笔记</h2>
            <p>为笔记命名并选择所属课程，创建后可以继续添加课件和内容。</p>
            <form onSubmit={(event) => void handleCreateNote(event)}>
              <label htmlFor="course-notes-course">所属课程</label>
              <select id="course-notes-course" value={selectedCourseId} onChange={(event) => setSelectedCourseId(event.target.value)}>
                {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
              </select>
              <label htmlFor="course-notes-new-name">笔记名称</label>
              <input id="course-notes-new-name" autoFocus value={newNoteName} onChange={(event) => setNewNoteName(event.target.value)} placeholder="例如：一元微积分" maxLength={120} />
              {newNoteError && <p className="course-notes-error" role="alert">{newNoteError}</p>}
              <button className="course-notes-dialog-submit" type="submit" disabled={!selectedCourseId || !newNoteName.trim() || creatingNote}>{creatingNote ? '正在创建…' : '创建并打开'}</button>
            </form>
          </section>
        </div>
      )}

      {courseDialogOpen && (
        <div className="course-notes-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !creatingCourse) setCourseDialogOpen(false) }}>
          <section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-notes-create-course-title">
            <button className="course-notes-dialog-close" type="button" onClick={() => setCourseDialogOpen(false)} disabled={creatingCourse} aria-label="关闭">×</button>
            <h2 id="course-notes-create-course-title">新建课程</h2>
            <p>先创建课程，再添加课件与笔记。</p>
            <form onSubmit={(event) => void handleCreateCourse(event)}>
              <label htmlFor="course-notes-create-name">课程名称</label>
              <input id="course-notes-create-name" autoFocus value={courseName} onChange={(event) => setCourseName(event.target.value)} placeholder="例如：数学分析" maxLength={120} />
              {createError && <p className="course-notes-error" role="alert">{createError}</p>}
              <button className="course-notes-dialog-submit" type="submit" disabled={!courseName.trim() || creatingCourse}>{creatingCourse ? '正在创建…' : '创建并打开'}</button>
            </form>
          </section>
        </div>
      )}
    </section>
  )
}
