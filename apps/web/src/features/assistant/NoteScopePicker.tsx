import { useEffect, useMemo, useRef, useState } from 'react'

import type { Course, Note } from '../../types'

/**
 * 锁定笔记的选择框：新建会话时挑一篇笔记作为这一轮提问的范围。
 * 两种找法并存 —— 按课程筛、按笔记名称搜，两者叠加生效。
 *
 * 笔记是按课程取的数据（noteApi.listNotes(courseId)），所以换课程时才按需拉取并缓存；
 * 当前课程的笔记上下文里已经有了，直接复用，不再重复请求。
 */
export function NoteScopePicker({ open, courses, currentCourseId, currentNotes, loadNotes, onPick, onClose }: {
  open: boolean
  courses: Course[]
  currentCourseId?: string
  /** 当前课程的笔记，上下文里已有，省一次请求 */
  currentNotes: Note[]
  /** 按课程拉取笔记；由页面注入，便于测试替换 */
  loadNotes: (courseId: string) => Promise<Note[]>
  onPick: (note: Note) => void
  onClose: () => void
}) {
  const [courseId, setCourseId] = useState<string>(currentCourseId ?? '')
  const [keyword, setKeyword] = useState('')
  const [cache, setCache] = useState<Record<string, Note[]>>({})
  const [loading, setLoading] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  /* loadNotes 由父组件内联传入，每次渲染都是新引用；用 ref 取，避免把加载 effect 拽着重跑 */
  const loadRef = useRef(loadNotes)
  loadRef.current = loadNotes

  const courseIds = useMemo(() => courses.map((course) => course.id), [courses])
  const courseNames = useMemo(() => new Map(courses.map((course) => [course.id, course.name])), [courses])

  /* 打开时复位：默认落在当前课程、清空搜索、聚焦搜索框 */
  useEffect(() => {
    if (!open) return
    setCourseId(currentCourseId ?? '')
    setKeyword('')
    setCache((previous) => (currentCourseId ? { ...previous, [currentCourseId]: currentNotes } : previous))
    const timer = window.setTimeout(() => searchRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open, currentCourseId, currentNotes])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  /* 按需拉取：选了哪门课就拉哪门课的笔记；「全部课程」则一次拉全（命中缓存的跳过） */
  useEffect(() => {
    if (!open) return
    const targets = courseId ? [courseId] : courseIds
    const missing = targets.filter((id) => !(id in cache) && id !== currentCourseId)
    if (missing.length === 0) return
    let alive = true
    setLoading(true)
    Promise.all(missing.map(async (id) => {
      try {
        return [id, await loadRef.current(id)] as const
      } catch {
        return [id, [] as Note[]] as const
      }
    })).then((pairs) => {
      if (!alive) return
      setCache((previous) => {
        const next = { ...previous }
        for (const [id, list] of pairs) next[id] = list
        return next
      })
      setLoading(false)
    })
    return () => { alive = false }
  }, [open, courseId, courseIds, cache, currentCourseId])

  const notes = useMemo(() => {
    const pool = courseId
      ? (courseId === currentCourseId ? currentNotes : (cache[courseId] ?? []))
      : courseIds.flatMap((id) => (id === currentCourseId ? currentNotes : (cache[id] ?? [])))
    const word = keyword.trim().toLowerCase()
    if (!word) return pool
    return pool.filter((note) => note.title.toLowerCase().includes(word))
  }, [courseId, courseIds, cache, currentCourseId, currentNotes, keyword])

  if (!open) return null

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card note-picker"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="选择要锁定的笔记"
      >
        <h3>锁定一篇笔记</h3>
        <p className="modal-hint">选好后，这一轮提问就只围绕这篇笔记作答。可以按课程找，也可以直接搜笔记名称。</p>

        <div className="note-picker-filters">
          <label className="note-picker-field">
            <span>课程</span>
            <select value={courseId} onChange={(event) => setCourseId(event.target.value)} aria-label="按课程筛选笔记">
              <option value="">全部课程</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>{course.name}</option>
              ))}
            </select>
          </label>
          <label className="note-picker-field">
            <span>搜索</span>
            <input
              ref={searchRef}
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索笔记名称"
              aria-label="搜索笔记名称"
            />
          </label>
        </div>

        <div className="note-picker-list">
          {loading && <p className="note-picker-empty">正在加载笔记…</p>}
          {!loading && notes.length === 0 && (
            <p className="note-picker-empty">
              {keyword.trim() ? '没有匹配的笔记，换个词试试' : '这里还没有笔记，先去整理课程笔记吧'}
            </p>
          )}
          {!loading && notes.map((note) => (
            <button
              key={note.id}
              type="button"
              className="note-picker-item"
              onClick={() => onPick(note)}
            >
              <span className="note-picker-title">{note.title}</span>
              {!courseId && <span className="note-picker-course">{courseNames.get(note.course_id) ?? ''}</span>}
            </button>
          ))}
        </div>

        <div className="modal-actions">
          <span className="note-picker-count">共 {notes.length} 篇</span>
          <button className="ghost-button" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
