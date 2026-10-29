import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { UnboundNotebookSummary } from '../api/notebook'
import { useWorkspace } from '../components/AppLayout'
import type { Course, DeletionPreview, NotebookSummary } from '../types'
import './CourseLibraryPage.css'

type CourseNotes = { course: Course; notes: NotebookSummary[]; error?: string }
type LibraryNote = NotebookSummary | (UnboundNotebookSummary & { course_id: null })

function serverDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`)
}

function noteUpdatedLabel(value: string): string {
  return serverDate(value).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function NoteCover({ variant, coverUrl }: { variant: number; coverUrl?: string | null }) {
  const kind = variant % 5
  return (
    <span className={`course-note-cover course-note-cover-${kind}`} aria-hidden="true">
      {coverUrl && <img className="course-note-cover-image" src={coverUrl} alt="" />}
      {!coverUrl && <svg viewBox="0 0 180 200" fill="none" focusable="false">
        {kind === 0 && <><path d="M24 158h132M42 173V42" stroke="#a1b5a0" strokeWidth="1.5" /><path d="M25 151c26-5 30-79 59-84 29-5 30 69 69 64" stroke="#2f5d45" strokeWidth="3" strokeLinecap="round" /><text x="141" y="58" fill="#2f5d45" fontFamily="serif" fontSize="28">∫</text></>}
        {kind === 1 && <><path d="M24 155h132" stroke="#c7bca9" strokeWidth="1.5" /><path d="M28 125c17 0 27-48 49-48 19 0 25 59 44 59 13 0 20-23 37-23" stroke="#b2684a" strokeWidth="3" strokeLinecap="round" /><circle cx="77" cy="77" r="4" fill="#b2684a" /><circle cx="121" cy="136" r="4" fill="#b2684a" /></>}
        {kind === 2 && <><path d="M24 158h132M42 173V42" stroke="#a3bab5" strokeWidth="1.5" /><path d="M43 148c26 0 30-70 57-70s32-17 54-17" stroke="#3d7265" strokeWidth="3" strokeLinecap="round" /><path d="M100 72v77" stroke="#3d7265" strokeWidth="1.5" strokeDasharray="5 5" /></>}
        {kind === 3 && <><path d="M24 119c27-31 53-31 80 0s53 31 80 0M24 132c27-31 53-31 80 0s53 31 80 0" stroke="#4a7b71" strokeWidth="2.5" /><text x="137" y="164" fill="#2f5d45" fontFamily="serif" fontSize="28">λ</text></>}
        {kind === 4 && <><path d="M24 143h132" stroke="#b5ab97" strokeWidth="2" /><path d="M43 143c10-63 84-63 94 0" stroke="#9f7755" strokeWidth="3" /><circle cx="43" cy="143" r="5" fill="#9f7755" /><circle cx="137" cy="143" r="5" fill="#9f7755" /></>}
      </svg>}
    </span>
  )
}

function NoteLink({ to, title, children, onClick }: { to: string; title: string; children: ReactNode; onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void }) {
  return <Link
    className="course-note-card"
    to={to}
    aria-label={`打开笔记：${title}`}
    onClick={onClick}
  >{children}</Link>
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
  const [libraryError, setLibraryError] = useState<string>()
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedNotebookIds, setSelectedNotebookIds] = useState<Set<string>>(() => new Set())
  const [bulkTargetCourseId, setBulkTargetCourseId] = useState('')
  const [bulkCoursePickerOpen, setBulkCoursePickerOpen] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [activeMenu, setActiveMenu] = useState<string>()
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number }>()
  const [activeCourseMenu, setActiveCourseMenu] = useState<string>()
  const [courseAction, setCourseAction] = useState<{ course: Course; kind: 'rename' } | { course: Course; kind: 'delete'; impact?: DeletionPreview; notebookCount: number }>()
  const [courseActionValue, setCourseActionValue] = useState('')
  const [courseActionBusy, setCourseActionBusy] = useState(false)
  const [courseActionError, setCourseActionError] = useState<string>()
  const [courseDeletionPreviewingId, setCourseDeletionPreviewingId] = useState<string>()
  const [activeCourseMenuPosition, setActiveCourseMenuPosition] = useState<{ left: number; top: number }>()
  const [actionNote, setActionNote] = useState<LibraryNote>()
  const [actionKind, setActionKind] = useState<'rename' | 'move' | 'delete'>()
  const [actionValue, setActionValue] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string>()
  const coverInputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const coverNoteRef = useRef<NotebookSummary | undefined>(undefined)
  const createAreaRef = useRef<HTMLDivElement>(null)
  const courseTriggerRef = useRef<HTMLButtonElement>(null)
  const noteTriggerRef = useRef<HTMLButtonElement>(null)
  const courseMenuRef = useRef<HTMLDivElement>(null)
  const courseMenuTriggerRef = useRef<HTMLButtonElement>(null)
  const bulkCoursePickerRef = useRef<HTMLDivElement>(null)
  const bulkCoursePickerTriggerRef = useRef<HTMLButtonElement>(null)
  const bulkCourseOptionRef = useRef<HTMLButtonElement>(null)

  function toggleCourseMenu(event: React.MouseEvent<HTMLButtonElement>, courseId: string) {
    if (activeCourseMenu === courseId) { setActiveCourseMenu(undefined); return }
    const heading = event.currentTarget.closest('.course-notes-group-heading')?.getBoundingClientRect()
    if (!heading) return
    const width = 164, height = 92, gap = 8, margin = 12
    const left = window.innerWidth - heading.right >= width + gap + margin
      ? heading.right + gap
      : heading.left >= width + gap + margin
        ? heading.left - width - gap
        : Math.min(window.innerWidth - width - margin, Math.max(margin, heading.right - width))
    const top = Math.min(window.innerHeight - height - margin, Math.max(margin, heading.bottom - height))
    courseMenuTriggerRef.current = event.currentTarget
    setActiveCourseMenuPosition({ left, top })
    setActiveCourseMenu(courseId)
  }

  async function deleteCourseImmediately(course: Course) {
    if (courseDeletionPreviewingId || courseActionBusy) return
    setActiveCourseMenu(undefined)
    setCourseDeletionPreviewingId(course.id)
    try {
      await api.deleteCourse(course.id)
      await refreshCourses()
      setGroups(current => current.filter(group => group.course.id !== course.id))
    } catch (cause) { setLibraryError(cause instanceof Error ? cause.message : '课程删除失败') }
    finally { setCourseDeletionPreviewingId(undefined) }
  }

  async function submitCourseAction(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (!courseAction || courseActionBusy) return
    setCourseActionBusy(true); setCourseActionError(undefined)
    try {
      let renamedCourseName: string | undefined
      if (courseAction.kind === 'rename') {
        const name = courseActionValue.trim()
        if (!name) return
        renamedCourseName = (await api.renameCourse(courseAction.course.id, name)).name
      } else {
        await api.deleteCourse(courseAction.course.id)
      }
      await refreshCourses()
      if (renamedCourseName) {
        setGroups(current => current.map(group => group.course.id === courseAction.course.id
          ? { ...group, course: { ...group.course, name: renamedCourseName! } }
          : group))
      } else {
        setGroups(current => current.filter(group => group.course.id !== courseAction.course.id))
      }
      setCourseAction(undefined)
      setCourseActionValue('')
    } catch (cause) { setCourseActionError(cause instanceof Error ? cause.message : '课程操作失败') }
    finally { setCourseActionBusy(false) }
  }

  function toggleCardMenu(event: React.MouseEvent<HTMLButtonElement>, noteId: string) {
    if (activeMenu === noteId) { setActiveMenu(undefined); return }
    const card = event.currentTarget.closest('.course-note-card-menuable')?.getBoundingClientRect()
    if (!card) return
    const menuWidth = 164
    const menuHeight = 158
    const gap = 8
    const margin = 12
    const left = window.innerWidth - card.right >= menuWidth + gap + margin
      ? card.right + gap
      : card.left >= menuWidth + gap + margin
        ? card.left - menuWidth - gap
        : Math.min(window.innerWidth - menuWidth - margin, Math.max(margin, card.right - menuWidth))
    const top = Math.min(window.innerHeight - menuHeight - margin, Math.max(margin, card.bottom - menuHeight))
    menuTriggerRef.current = event.currentTarget
    setMenuPosition({ left, top })
    setActiveMenu(noteId)
  }

  useEffect(() => {
    if (!activeMenu) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || menuTriggerRef.current?.contains(target)) return
      setActiveMenu(undefined)
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') { setActiveMenu(undefined); menuTriggerRef.current?.focus() }
    }
    function closeMenu() { setActiveMenu(undefined) }
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', closeMenu, true)
    window.addEventListener('resize', closeMenu)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', closeMenu, true)
      window.removeEventListener('resize', closeMenu)
    }
  }, [activeMenu])

  useEffect(() => {
    if (!activeCourseMenu) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (courseMenuRef.current?.contains(target) || courseMenuTriggerRef.current?.contains(target)) return
      setActiveCourseMenu(undefined)
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') { setActiveCourseMenu(undefined); courseMenuTriggerRef.current?.focus() }
    }
    function closeMenu() { setActiveCourseMenu(undefined) }
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', closeMenu, true)
    window.addEventListener('resize', closeMenu)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', closeMenu, true)
      window.removeEventListener('resize', closeMenu)
    }
  }, [activeCourseMenu])

  useEffect(() => {
    if (!bulkCoursePickerOpen) return
    bulkCourseOptionRef.current?.focus()
    function onPointerDown(event: PointerEvent) {
      if (!bulkCoursePickerRef.current?.contains(event.target as Node)) setBulkCoursePickerOpen(false)
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setBulkCoursePickerOpen(false)
        bulkCoursePickerTriggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [bulkCoursePickerOpen])

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
      else if (notePopoverOpen && !creatingNote) { setNotePopoverOpen(false); noteTriggerRef.current?.focus() }
      else if (coursePopoverOpen && !creatingCourse) { setCoursePopoverOpen(false); courseTriggerRef.current?.focus() }
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
      navigate(`/notebooks/unbound/${notebook.id}`)
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

  async function createBlankNotebook(courseId: string) {
    setLibraryError(undefined)
    try {
      const notebook = await api.createNotebook(courseId, '未命名笔记')
      navigate(`/courses/${courseId}/notebooks/${notebook.id}`)
    } catch (cause) { setLibraryError(cause instanceof Error ? cause.message : '笔记创建失败') }
  }

  async function submitCardAction(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (!actionNote || !actionKind || actionBusy) return
    setActionBusy(true); setActionError(undefined)
    try {
      if (!actionNote.course_id) {
        if (actionKind === 'rename') {
          const renamed = await api.renameUnboundNotebook(actionNote.id, actionValue.trim())
          setUnboundNotes(current => current.map(note => note.id === actionNote.id ? renamed : note))
        } else if (actionKind === 'move') {
          const bound = await api.bindNotebook(actionNote.id, actionValue)
          setGroups(current => current.map(group => group.course.id === actionValue ? { ...group, notes: [...group.notes, bound] } : group))
          setUnboundNotes(current => current.filter(note => note.id !== actionNote.id))
        } else {
          await api.deleteUnboundNotebook(actionNote.id)
          setUnboundNotes(current => current.filter(note => note.id !== actionNote.id))
        }
        setSelectedNotebookIds(current => { const next = new Set(current); next.delete(actionNote.id); return next })
        setActionNote(undefined); setActionKind(undefined)
        return
      }
      if (actionKind === 'rename') await api.renameNotebook(actionNote.course_id, actionNote.id, actionValue.trim())
      else if (actionKind === 'move') await api.moveNotebook(actionNote.id, actionValue)
      else {
        await api.deleteNotebook(actionNote.course_id, actionNote.id)
        setGroups((current) => current.map((group) => ({ ...group, notes: group.notes.filter((note) => note.id !== actionNote.id) })))
        setActionNote(undefined); setActionKind(undefined)
        return
      }
      if (actionKind === 'move') {
        setGroups((current) => current.map((group) => ({ ...group, notes: group.notes.filter((note) => note.id !== actionNote.id) })))
        setSelectedNotebookIds(current => { const next = new Set(current); next.delete(actionNote.id); return next })
      } else {
        setGroups((current) => current.map((group) => ({ ...group, notes: group.notes.map((note) => note.id === actionNote.id ? { ...note, title: actionValue.trim() } : note) })))
      }
      setActionNote(undefined); setActionKind(undefined)
    } catch (cause) { setActionError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setActionBusy(false) }
  }

  async function deleteCardNote(note: LibraryNote) {
    if (actionBusy) return
    setActionBusy(true); setLibraryError(undefined)
    try {
      if (note.course_id) {
        await api.deleteNotebook(note.course_id, note.id)
        setGroups(current => current.map(group => ({ ...group, notes: group.notes.filter(item => item.id !== note.id) })))
      } else {
        await api.deleteUnboundNotebook(note.id)
        setUnboundNotes(current => current.filter(item => item.id !== note.id))
      }
      setSelectedNotebookIds(current => { const next = new Set(current); next.delete(note.id); return next })
      setActiveMenu(undefined)
    } catch (cause) {
      setLibraryError(cause instanceof Error ? cause.message : '笔记删除失败')
    } finally { setActionBusy(false) }
  }

  function toggleNotebookSelection(notebookId: string) {
    setSelectedNotebookIds(current => {
      const next = new Set(current)
      if (next.has(notebookId)) next.delete(notebookId)
      else next.add(notebookId)
      return next
    })
  }

  async function runBulkAction(action: 'move' | 'delete') {
    if (!selectedNotebookIds.size || bulkBusy || (action === 'move' && bulkTargetCourseId === '')) return
    setBulkBusy(true); setLibraryError(undefined)
    try {
      const result = await api.bulkManageNotebooks(
        [...selectedNotebookIds], action,
        action === 'move' ? (bulkTargetCourseId === '__unbound__' ? null : bulkTargetCourseId) : null,
      )
      const [unbound, refreshedGroups] = await Promise.all([
        api.listUnboundNotebooks(),
        Promise.all(courses.map(async course => ({ course, notes: await api.listNotebooks(course.id) }))),
      ])
      setUnboundNotes(unbound)
      setGroups(refreshedGroups)
      setSelectedNotebookIds(new Set())
      setSelectionMode(false)
      setLibraryError(action === 'move' ? `已移动 ${result.affected} 篇笔记。` : `已将 ${result.affected} 篇笔记移入回收站。`)
    } catch (cause) {
      setLibraryError(cause instanceof Error ? cause.message : action === 'move' ? '批量移动失败' : '批量删除失败')
    } finally { setBulkBusy(false) }
  }

  function beginBulkSelection(notebookId?: string) {
    setSelectionMode(true)
    if (notebookId) setSelectedNotebookIds(current => new Set(current).add(notebookId))
  }

  async function handleCoverChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    const selectedNote = coverNoteRef.current
    if (!file || !selectedNote) return
    try {
      await api.uploadNotebookCover(selectedNote.id, file)
      setGroups((current) => current.map((group) => ({ ...group, notes: group.notes.map((note) => note.id === selectedNote.id ? { ...note, cover_url: `/api/v1/notebooks/${selectedNote.id}/cover?v=${Date.now()}` } : note) })))
    } catch (cause) { setLibraryError(cause instanceof Error ? cause.message : '封面上传失败') }
    coverNoteRef.current = undefined
  }

  function chooseCover(note: NotebookSummary) {
    coverNoteRef.current = note
    if (coverInputRef.current) { coverInputRef.current.value = ''; coverInputRef.current.click() }
  }

  return (
    <section className="course-notes-page page-enter" aria-label="按课程分组的笔记">
      {libraryError && <p className="course-notes-error" role="alert">{libraryError}</p>}
      <div className="course-notes-toolbar">
        <label className="course-notes-search">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="10.8" cy="10.8" r="7.1" /><path d="m16 16 5 5" /></svg>
          <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" aria-label="搜索笔记或课程" placeholder="搜索笔记或课程…" />
        </label>
        <div className="course-notes-create" ref={createAreaRef}>
          <button className={`course-notes-create-trigger course-notes-create-secondary${selectionMode ? ' is-active' : ''}`} type="button" aria-pressed={selectionMode} onClick={() => { setSelectionMode(value => !value); setSelectedNotebookIds(new Set()) }}>{selectionMode ? '退出批量管理' : '批量管理'}</button>
          <button ref={courseTriggerRef} className="course-notes-create-trigger course-notes-create-secondary" type="button" onClick={openCreateCourse} aria-expanded={coursePopoverOpen} aria-controls={coursePopoverOpen ? 'course-notes-course-popover' : undefined}>新建课程文件夹</button>
          <button ref={noteTriggerRef} className="course-notes-create-trigger" type="button" onClick={openCreateNote} aria-expanded={notePopoverOpen} aria-controls={notePopoverOpen ? 'course-notes-note-popover' : undefined}><span aria-hidden="true">＋</span> 新建笔记</button>
          {coursePopoverOpen && <form id="course-notes-course-popover" className="course-notes-create-popover" onSubmit={(event) => void handleCreateCourse(event)}>
            <label htmlFor="course-notes-create-name">课程名称</label>
            <input id="course-notes-create-name" autoFocus value={courseName} onChange={(event) => setCourseName(event.target.value)} placeholder="例如：数学分析" maxLength={120} />
            {createError && <p className="course-notes-error" role="alert">{createError}</p>}
            <button className="course-notes-dialog-submit" type="submit" disabled={!courseName.trim() || creatingCourse}>{creatingCourse ? '正在创建…' : '确认新建'}</button>
          </form>}
          {notePopoverOpen && <form id="course-notes-note-popover" className="course-notes-create-popover" onSubmit={(event) => void handleCreateNote(event)}>
            <label htmlFor="course-notes-create-note-name">笔记名称</label>
            <input id="course-notes-create-note-name" autoFocus value={noteName} onChange={(event) => setNoteName(event.target.value)} placeholder="例如：一元微积分" maxLength={120} />
            {noteError && <p className="course-notes-error" role="alert">{noteError}</p>}
            <button className="course-notes-dialog-submit" type="submit" disabled={!noteName.trim() || creatingNote}>{creatingNote ? '正在创建…' : '确认新建'}</button>
          </form>}
        </div>
      </div>

      {selectionMode && <div className="course-bulk-toolbar" role="region" aria-label="批量管理笔记">
        <span className="course-bulk-count">已选 <strong>{selectedNotebookIds.size}</strong> 篇</span>
        <button type="button" className="course-bulk-select-all" onClick={() => {
          const ids = [...visibleUnboundNotes.map(note => note.id), ...visibleGroups.flatMap(group => group.notes.map(note => note.id))]
          setSelectedNotebookIds(new Set(ids))
        }}>全选当前结果</button>
        <div className="course-bulk-target">
          <span>移动到</span>
          <div className="course-bulk-picker" ref={bulkCoursePickerRef}>
            <button ref={bulkCoursePickerTriggerRef} type="button" className="course-bulk-picker-trigger" aria-haspopup="listbox" aria-expanded={bulkCoursePickerOpen} aria-controls="course-bulk-course-options" onClick={() => setBulkCoursePickerOpen(open => !open)} onKeyDown={event => { if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setBulkCoursePickerOpen(true) } }}>
              <span className={bulkTargetCourseId ? '' : 'is-placeholder'}>{bulkTargetCourseId === '__unbound__' ? '未分类' : courses.find(course => course.id === bulkTargetCourseId)?.name ?? '选择课程'}</span>
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 6 4.5 4 4.5-4" /></svg>
            </button>
            {bulkCoursePickerOpen && <div id="course-bulk-course-options" className="course-bulk-picker-options" role="listbox" aria-label="选择目标归属">
              <button ref={bulkCourseOptionRef} type="button" role="option" aria-selected={bulkTargetCourseId === '__unbound__'} className={bulkTargetCourseId === '__unbound__' ? 'is-selected' : ''} onClick={() => { setBulkTargetCourseId('__unbound__'); setBulkCoursePickerOpen(false); bulkCoursePickerTriggerRef.current?.focus() }}><span>未分类</span>{bulkTargetCourseId === '__unbound__' && <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3.2 3.2L13 4.5" /></svg>}</button>
              {courses.map(course => <button key={course.id} type="button" role="option" aria-selected={bulkTargetCourseId === course.id} className={bulkTargetCourseId === course.id ? 'is-selected' : ''} onClick={() => { setBulkTargetCourseId(course.id); setBulkCoursePickerOpen(false); bulkCoursePickerTriggerRef.current?.focus() }}><span>{course.name}</span>{bulkTargetCourseId === course.id && <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3.2 3.2L13 4.5" /></svg>}</button>)}
            </div>}
          </div>
        </div>
        <button type="button" className="course-bulk-move" disabled={!selectedNotebookIds.size || !bulkTargetCourseId || bulkBusy} onClick={() => void runBulkAction('move')}>{bulkBusy ? '处理中…' : '批量移动'}</button>
        <button type="button" className="course-bulk-delete" disabled={!selectedNotebookIds.size || bulkBusy} onClick={() => void runBulkAction('delete')}>{bulkBusy ? '处理中…' : '批量删除'}</button>
      </div>}

      {coursesLoading || notesLoading ? (
        <div className="course-notes-loading" role="status" aria-label="正在读取课程笔记">
          <span className="course-notes-loading-title" />
          <div className="course-notes-loading-grid">{[0, 1, 2].map((item) => <span key={item} />)}</div>
        </div>
      ) : visibleGroups.length === 0 && visibleUnboundNotes.length === 0 && query.trim() ? (
        <div className="course-notes-empty"><h2>没有找到相关笔记</h2><p>试试其他笔记名称或课程名称。</p></div>
      ) : visibleGroups.length === 0 && visibleUnboundNotes.length === 0 ? (
        <div className="course-notes-empty"><h2>还没有课程</h2><p>先新建课程文件夹，再在课程中创建空白笔记。</p><button type="button" onClick={openCreateCourse}>新建课程文件夹</button></div>
      ) : (
        <div className="course-notes-groups">
          {visibleUnboundNotes.length > 0 && <section className="course-notes-group" aria-labelledby="course-notes-unbound">
            <div className="course-notes-group-heading"><div className="course-notes-group-title"><h2 id="course-notes-unbound">未分类</h2><span>{visibleUnboundNotes.length} 篇笔记</span></div></div>
            <div className="course-notes-grid">
              {visibleUnboundNotes.map((note, noteIndex) => <article className={`course-note-card-unbound course-note-card-menuable${activeMenu === note.id ? ' is-menu-open' : ''}${selectedNotebookIds.has(note.id) ? ' is-selected' : ''}`} key={note.id} onContextMenu={event => { event.preventDefault(); beginBulkSelection(note.id) }}>
                {selectionMode && <button type="button" role="checkbox" aria-checked={selectedNotebookIds.has(note.id)} aria-label={`选择笔记：${note.title}`} className="course-note-select" onClick={() => toggleNotebookSelection(note.id)}><span /></button>}
                <NoteLink to={`/notebooks/unbound/${note.id}`} title={note.title} onClick={event => { if (selectionMode) { event.preventDefault(); toggleNotebookSelection(note.id) } }}>
                  <NoteCover variant={noteIndex} coverUrl={note.cover_url} />
                  <strong title={note.title}>{note.title}</strong>
                </NoteLink>
                <div className="course-note-card-footer">
                  <time className="course-note-card-date" dateTime={note.updated_at}>{noteUpdatedLabel(note.updated_at)}</time>
                  <button className="course-note-menu-trigger" type="button" aria-label={`“${note.title}”的更多操作`} aria-expanded={activeMenu === note.id} aria-controls={activeMenu === note.id ? 'course-note-menu' : undefined} onClick={event => toggleCardMenu(event, note.id)}><svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg></button>
                </div>
                {activeMenu === note.id && menuPosition && createPortal(<div id="course-note-menu" className="course-note-menu" role="menu" ref={menuRef} style={menuPosition}>
                  <button type="button" role="menuitem" onClick={() => { setActionNote({ ...note, course_id: null }); setActionKind('rename'); setActionValue(note.title); setActionError(undefined); setActiveMenu(undefined) }}>重命名</button>
                  <button type="button" role="menuitem" disabled={!courses.length} onClick={() => { setActionNote({ ...note, course_id: null }); setActionKind('move'); setActionValue(''); setActionError(undefined); setActiveMenu(undefined) }}>移入课程</button>
                  <button type="button" role="menuitem" className="course-note-menu-danger" disabled={actionBusy} onClick={() => void deleteCardNote({ ...note, course_id: null })}>删除</button>
                </div>, document.body)}
              </article>)}
            </div>
          </section>}
          {visibleGroups.map(({ course, notes, error }, groupIndex) => (
            <section className="course-notes-group" key={course.id} aria-labelledby={`course-notes-${course.id}`}>
              <div className="course-notes-group-heading">
                <div className="course-notes-group-title"><h2 id={`course-notes-${course.id}`}>{course.name}</h2><span>{notes.length} 篇笔记</span></div>
                <button className="course-group-menu-trigger" type="button" aria-label={`课程“${course.name}”的更多操作`} aria-expanded={activeCourseMenu === course.id} aria-controls={activeCourseMenu === course.id ? 'course-group-menu' : undefined} onClick={event => toggleCourseMenu(event, course.id)}><span aria-hidden="true"><i /><i /><i /></span></button>
                {activeCourseMenu === course.id && activeCourseMenuPosition && createPortal(<div id="course-group-menu" className="course-note-menu course-group-menu" role="menu" ref={courseMenuRef} style={activeCourseMenuPosition}>
                  <button type="button" role="menuitem" onClick={() => { setCourseAction({ course, kind: 'rename' }); setCourseActionValue(course.name); setCourseActionError(undefined); setActiveCourseMenu(undefined) }}>重命名课程</button>
                  <button type="button" role="menuitem" className="course-note-menu-danger" disabled={Boolean(courseDeletionPreviewingId)} onClick={() => void deleteCourseImmediately(course)}>{courseDeletionPreviewingId === course.id ? '正在删除…' : '删除课程'}</button>
                </div>, document.body)}
              </div>
              {error && <p className="course-notes-error" role="alert">{course.name}的笔记读取失败：{error}</p>}
              {!error && notes.length > 0 && <div className="course-notes-grid">
              {notes.map((note, noteIndex) => (
                  <article className={`course-note-card-unbound course-note-card-menuable${activeMenu === note.id ? ' is-menu-open' : ''}${selectedNotebookIds.has(note.id) ? ' is-selected' : ''}`} key={note.id} onContextMenu={event => { event.preventDefault(); beginBulkSelection(note.id) }}>
                    {selectionMode && <button type="button" role="checkbox" aria-checked={selectedNotebookIds.has(note.id)} aria-label={`选择笔记：${note.title}`} className="course-note-select" onClick={() => toggleNotebookSelection(note.id)}><span /></button>}
                    <NoteLink to={`/courses/${course.id}/notebooks/${note.id}`} title={note.title} onClick={event => { if (selectionMode) { event.preventDefault(); toggleNotebookSelection(note.id) } }}>
                      <NoteCover variant={groupIndex * 3 + noteIndex} coverUrl={note.cover_url} />
                      <strong title={note.title}>{note.title}</strong>
                    </NoteLink>
                    <div className="course-note-card-footer">
                      <time className="course-note-card-date" dateTime={note.updated_at}>{noteUpdatedLabel(note.updated_at)}</time>
                      <button className="course-note-menu-trigger" type="button" aria-label={`“${note.title}”的更多操作`} aria-expanded={activeMenu === note.id} aria-controls={activeMenu === note.id ? 'course-note-menu' : undefined} onClick={(event) => toggleCardMenu(event, note.id)}>
                        <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
                      </button>
                    </div>
                    {activeMenu === note.id && menuPosition && createPortal(<div id="course-note-menu" className="course-note-menu" role="menu" ref={menuRef} style={menuPosition}>
                  <button type="button" role="menuitem" onClick={() => { setActionNote(note); setActionKind('rename'); setActionValue(note.title); setActionError(undefined); setActiveMenu(undefined) }}>重命名</button>
                      <button type="button" role="menuitem" onClick={() => { setActionNote(note); setActionKind('move'); setActionValue(''); setActionError(undefined); setActiveMenu(undefined) }}>移动到其他课程</button>
                      <button type="button" role="menuitem" onClick={() => { chooseCover(note); setActiveMenu(undefined) }}>添加封面</button>
                  <button type="button" role="menuitem" className="course-note-menu-danger" disabled={actionBusy} onClick={() => void deleteCardNote(note)}>删除</button>
                    </div>, document.body)}
                  </article>
                ))}
                <button className="course-note-create-card" type="button" onClick={() => void createBlankNotebook(course.id)} aria-label={`在${course.name}中新建空白笔记`}><span aria-hidden="true">＋</span><strong>新建空白笔记</strong></button>
              </div>}
              {notes.length === 0 && !error && <div className="course-notes-grid"><button className="course-note-create-card" type="button" onClick={() => void createBlankNotebook(course.id)} aria-label={`在${course.name}中新建空白笔记`}><span aria-hidden="true">＋</span><strong>新建空白笔记</strong></button></div>}
            </section>
          ))}
        </div>
      )}
      {bindNote && (
        <div className="course-notes-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !bindingNote) setBindNote(undefined) }}>
          <section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-notes-bind-title">
            <button className="course-notes-dialog-close" type="button" onClick={() => setBindNote(undefined)} disabled={bindingNote} aria-label="关闭">×</button>
            <h2 id="course-notes-bind-title">归入课程</h2>
            <p>为“{bindNote.title}”选择一个课程文件夹。</p>
            <form onSubmit={(event) => void handleBindNote(event)}>
              <label htmlFor="course-notes-bind-course">课程文件夹</label>
              <select id="course-notes-bind-course" value={bindCourseId} onChange={(event) => setBindCourseId(event.target.value)}>
                {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
              </select>
              {bindError && <p className="course-notes-error" role="alert">{bindError}</p>}
              <button className="course-notes-dialog-submit" type="submit" disabled={!bindCourseId || bindingNote}>{bindingNote ? '正在绑定…' : '确认绑定'}</button>
            </form>
          </section>
        </div>
      )}
      <input ref={coverInputRef} className="course-note-cover-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => void handleCoverChange(event)} />
      {actionNote && actionKind && actionKind !== 'delete' && <div className="course-notes-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !actionBusy) setActionNote(undefined) }}>
          <section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-note-action-title">
          <button className="course-notes-dialog-close" type="button" onClick={() => setActionNote(undefined)} disabled={actionBusy} aria-label="关闭">×</button>
          <h2 id="course-note-action-title">{actionKind === 'rename' ? '重命名笔记' : '移动到其他课程'}</h2>
          <p>{actionNote.title}</p>
          <form onSubmit={(event) => void submitCardAction(event)}>
            {actionKind === 'rename' ? <><label htmlFor="course-note-action-value">笔记名称</label><input id="course-note-action-value" autoFocus maxLength={200} value={actionValue} onChange={(event) => setActionValue(event.target.value)} /></> : <><label htmlFor="course-note-action-value">目标课程</label><select id="course-note-action-value" autoFocus value={actionValue} onChange={(event) => setActionValue(event.target.value)}><option value="">请选择课程</option>{courses.filter((course) => !actionNote.course_id || course.id !== actionNote.course_id).map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}</select></>}
            {actionError && <p className="course-notes-error" role="alert">{actionError}</p>}
            <button className="course-notes-dialog-submit" type="submit" disabled={actionBusy || (actionKind === 'rename' ? !actionValue.trim() : !actionValue)}>{actionBusy ? '正在保存…' : '确认'}</button>
          </form>
        </section>
      </div>}
      {courseAction?.kind === 'rename' && <div className="course-notes-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !courseActionBusy) setCourseAction(undefined) }}><section className="course-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="course-action-title"><button className="course-notes-dialog-close" type="button" onClick={() => setCourseAction(undefined)} disabled={courseActionBusy} aria-label="关闭">×</button><h2 id="course-action-title">重命名课程</h2><form onSubmit={event => void submitCourseAction(event)}><label htmlFor="course-action-name">课程名称</label><input id="course-action-name" autoFocus maxLength={200} value={courseActionValue} onChange={event => setCourseActionValue(event.target.value)} />{courseActionError && <p className="course-notes-error" role="alert">{courseActionError}</p>}<button className="course-notes-dialog-submit" type="submit" disabled={!courseActionValue.trim() || courseActionBusy}>{courseActionBusy ? '正在保存…' : '保存'}</button></form></section></div>}
    </section>
  )
}
