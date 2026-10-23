import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { UnboundNotebookSummary } from '../api/notebook'
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
  const { courses, coursesLoading, createCourse, refreshCourses } = useWorkspace()
  const navigate = useNavigate()
  const location = useLocation()
  const [groups, setGroups] = useState<CourseNotes[]>([])
  const [notesLoading, setNotesLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [coursePopoverOpen, setCoursePopoverOpen] = useState(false)
  const [courseName, setCourseName] = useState('')
  const [creatingCourse, setCreatingCourse] = useState(false)
  const [createError, setCreateError] = useState<string>()
  const [notePopoverOpen, setNotePopoverOpen] = useState(false)
  const [noteName, setNoteName] = useState('')
  const [creatingNote, setCreatingNote] = useState(false)
  const [noteError, setNoteError] = useState<string>()
  const [unboundNotes, setUnboundNotes] = useState<UnboundNotebookSummary[]>([])
  const [bindNote, setBindNote] = useState<UnboundNotebookSummary>()
  const [bindCourseId, setBindCourseId] = useState('')
  const [bindingNote, setBindingNote] = useState(false)
  const [bindError, setBindError] = useState<string>()
  const createAreaRef = useRef<HTMLDivElement>(null)

  // 承接侧边栏快捷新建入口。
  useEffect(() => {
    const state = location.state as { openCreateCourse?: boolean; openCreateNote?: boolean } | null
    if (!state?.openCreateCourse && !state?.openCreateNote) return
    if (state.openCreateNote) {
      setCoursePopoverOpen(false)
      setNoteName('')
      setNoteError(undefined)
      setNotePopoverOpen(true)
    } else {
      setNotePopoverOpen(false)
      setCreateError(undefined)
      setCoursePopoverOpen(true)
    }
    navigate('/courses', { replace: true, state: null })
  }, [location.state, navigate])

  useEffect(() => {
    if (coursesLoading) return
    let active = true
    setNotesLoading(true)
    void Promise.all([
      Promise.all(courses.map(async (course): Promise<CourseNotes> => {
      try { return { course, notes: await api.listNotebooks(course.id) } }
      catch (cause) { return { course, notes: [], error: cause instanceof Error ? cause.message : '笔记读取失败' } }
      })),
      api.listUnboundNotebooks().catch((): UnboundNotebookSummary[] => []),
    ]).then(([result, unbound]) => { if (active) { setGroups(result); setUnboundNotes(unbound) } })
      .finally(() => { if (active) setNotesLoading(false) })
    return () => { active = false }
  }, [courses, coursesLoading])

  useEffect(() => {
    if (!coursePopoverOpen && !notePopoverOpen && !bindNote) return
    function onEscape(event: globalThis.KeyboardEvent) {
      if (event.key !== 'Escape') return
      if (bindNote && !bindingNote) setBindNote(undefined)
      else if (notePopoverOpen && !creatingNote) setNotePopoverOpen(false)
      else if (coursePopoverOpen && !creatingCourse) setCoursePopoverOpen(false)
    }
    window.addEventListener('keydown', onEscape)
    return () => window.removeEventListener('keydown', onEscape)
  }, [bindNote, bindingNote, coursePopoverOpen, creatingCourse, notePopoverOpen, creatingNote])

  useEffect(() => {
    if (!coursePopoverOpen && !notePopoverOpen) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) return
      if (createAreaRef.current?.contains(target)) return
      setCoursePopoverOpen(false)
      setNotePopoverOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [coursePopoverOpen, notePopoverOpen])

  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return groups.map(({ course, notes, error }) => ({
      course, error,
      notes: needle && !course.name.toLocaleLowerCase().includes(needle)
        ? notes.filter((note) => note.title.toLocaleLowerCase().includes(needle))
        : notes,
    })).filter(({ course, notes }) => !needle || course.name.toLocaleLowerCase().includes(needle) || notes.length > 0)
  }, [groups, query])

  const visibleUnboundNotes = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return unboundNotes.filter((note) => !needle || note.title.toLocaleLowerCase().includes(needle))
  }, [unboundNotes, query])

  async function handleCreateCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!courseName.trim() || creatingCourse) return
    setCreatingCourse(true)
    setCreateError(undefined)
    try {
      await createCourse(courseName.trim())
      await refreshCourses()
      setCoursePopoverOpen(false)
      setCourseName('')
    } catch (cause) {
      setCreateError(cause instanceof Error ? cause.message : '课程创建失败，请重试。')
    } finally { setCreatingCourse(false) }
  }

  function openCreateCourse() {
    setNotePopoverOpen(false)
    setCreateError(undefined)
    if (coursePopoverOpen) setCoursePopoverOpen(false)
    else setCoursePopoverOpen(true)
  }

  function openCreateNote() {
    setCoursePopoverOpen(false)
    if (notePopoverOpen) setNotePopoverOpen(false)
    else { setNoteName(''); setNoteError(undefined); setNotePopoverOpen(true) }
  }

  async function handleCreateNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!noteName.trim() || creatingNote) return
    setCreatingNote(true)
    setNoteError(undefined)
    try {
      const notebook = await api.createUnboundNotebook(noteName.trim())
      setUnboundNotes((current) => [notebook, ...current])
      setNotePopoverOpen(false)
      setNoteName('')
    } catch (cause) {
      setNoteError(cause instanceof Error ? cause.message : '笔记创建失败，请重试。')
    } finally { setCreatingNote(false) }
  }

  async function handleBindNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!bindNote || !bindCourseId || bindingNote) return
    setBindingNote(true)
    setBindError(undefined)
    try {
      const bound = await api.bindNotebook(bindNote.id, bindCourseId)
      setUnboundNotes((current) => current.filter((note) => note.id !== bindNote.id))
      setGroups((current) => current.map((group) => group.course.id === bindCourseId
        ? { ...group, notes: [...group.notes, bound] }
        : group))
      setBindNote(undefined)
      navigate(`/courses/${bindCourseId}/notebooks/${bound.id}`)
    } catch (cause) {
      setBindError(cause instanceof Error ? cause.message : '绑定失败，请重试。')
    } finally { setBindingNote(false) }
  }

  return (
    <section className="course-notes-page page-enter" aria-label="按课程分组的笔记">
      <div className="course-notes-toolbar">
        <label className="course-notes-search">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="10.8" cy="10.8" r="7.1" /><path d="m16 16 5 5" /></svg>
          <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" aria-label="搜索笔记或课程" placeholder="搜索笔记或课程…" />
        </label>
        <div className="course-notes-create" ref={createAreaRef}>
          <button className="course-notes-create-trigger course-notes-create-secondary" type="button" onClick={openCreateCourse} aria-expanded={coursePopoverOpen}>新建课程</button>
          <button className="course-notes-create-trigger" type="button" onClick={openCreateNote} aria-expanded={notePopoverOpen}><span aria-hidden="true">＋</span> 新建笔记</button>
          {coursePopoverOpen && <form className="course-notes-create-popover" onSubmit={(event) => void handleCreateCourse(event)}>
            <label htmlFor="course-notes-create-name">课程名称</label>
            <input id="course-notes-create-name" autoFocus value={courseName} onChange={(event) => setCourseName(event.target.value)} placeholder="例如：数学分析" maxLength={120} />
            {createError && <p className="course-notes-error" role="alert">{createError}</p>}
            <button className="course-notes-dialog-submit" type="submit" disabled={!courseName.trim() || creatingCourse}>{creatingCourse ? '正在创建…' : '确认新建'}</button>
          </form>}
          {notePopoverOpen && <form className="course-notes-create-popover" onSubmit={(event) => void handleCreateNote(event)}>
            <label htmlFor="course-notes-create-note-name">笔记名称</label>
            <input id="course-notes-create-note-name" autoFocus value={noteName} onChange={(event) => setNoteName(event.target.value)} placeholder="例如：一元微积分" maxLength={120} />
            {noteError && <p className="course-notes-error" role="alert">{noteError}</p>}
            <button className="course-notes-dialog-submit" type="submit" disabled={!noteName.trim() || creatingNote}>{creatingNote ? '正在创建…' : '确认新建'}</button>
          </form>}
        </div>
      </div>

      {coursesLoading || notesLoading ? (
        <div className="course-notes-loading" role="status" aria-label="正在读取课程笔记">
          <span className="course-notes-loading-title" />
          <div className="course-notes-loading-grid">{[0, 1, 2].map((item) => <span key={item} />)}</div>
        </div>
      ) : visibleGroups.length === 0 && visibleUnboundNotes.length === 0 && query.trim() ? (
        <div className="course-notes-empty"><h2>没有找到相关笔记</h2><p>试试其他笔记名称或课程名称。</p></div>
      ) : visibleGroups.length === 0 && visibleUnboundNotes.length === 0 ? (
        <div className="course-notes-empty"><h2>还没有课程</h2><p>创建课程，或先新建一篇空白笔记。</p><button type="button" onClick={openCreateCourse}>新建课程</button></div>
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
          {visibleUnboundNotes.length > 0 && <section className="course-notes-group" aria-labelledby="course-notes-unbound">
            <div className="course-notes-group-heading"><h2 id="course-notes-unbound">未绑定课程</h2><span>{visibleUnboundNotes.length} 篇笔记</span></div>
            <div className="course-notes-grid">
              {visibleUnboundNotes.map((note, noteIndex) => <article className="course-note-card course-note-card-unbound" key={note.id}>
                <NoteCover variant={noteIndex} courseName="" />
                <strong title={note.title}>{note.title}</strong>
                <button type="button" onClick={() => { setBindNote(note); setBindCourseId(courses[0]?.id ?? ''); setBindError(undefined) }} disabled={!courses.length} aria-label={`为“${note.title}”绑定课程`}>绑定课程</button>
              </article>)}
            </div>
          </section>}
        </div>
      )}
      {bindNote && (
        <div className="course-notes-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !bindingNote) setBindNote(undefined) }}>
          <section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-notes-bind-title">
            <button className="course-notes-dialog-close" type="button" onClick={() => setBindNote(undefined)} disabled={bindingNote} aria-label="关闭">×</button>
            <h2 id="course-notes-bind-title">绑定课程</h2>
            <p>为“{bindNote.title}”选择一门课程。</p>
            <form onSubmit={(event) => void handleBindNote(event)}>
              <label htmlFor="course-notes-bind-course">所属课程</label>
              <select id="course-notes-bind-course" value={bindCourseId} onChange={(event) => setBindCourseId(event.target.value)}>
                {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
              </select>
              {bindError && <p className="course-notes-error" role="alert">{bindError}</p>}
              <button className="course-notes-dialog-submit" type="submit" disabled={!bindCourseId || bindingNote}>{bindingNote ? '正在绑定…' : '确认绑定'}</button>
            </form>
          </section>
        </div>
      )}
    </section>
  )
}
