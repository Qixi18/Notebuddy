import { useEffect, useMemo, useRef, useState } from 'react'

import type { Course, NotebookSummary } from '../../types'

/**
 * 锁定 Notebook 的选择框：新建会话时选择这一轮提问的范围。
 * 两种找法并存 —— 按课程筛、按 Notebook 名称搜，两者叠加生效。
 *
 * Notebook 按课程按需读取并缓存；当前课程的数据由父页面直接提供。
 */
export function NoteScopePicker({ open, courses, currentCourseId, currentNotebooks, loadNotebooks, onPick, onClose }: {
  open: boolean
  courses: Course[]
  currentCourseId?: string
  /** 当前课程的 Notebook，上下文里已有，省一次请求 */
  currentNotebooks: NotebookSummary[]
  /** 按课程拉取 Notebook；由页面注入，便于测试替换 */
  loadNotebooks: (courseId: string) => Promise<NotebookSummary[]>
  onPick: (notebook: NotebookSummary) => void
  onClose: () => void
}) {
  const [courseId, setCourseId] = useState<string>(currentCourseId ?? '')
  const [keyword, setKeyword] = useState('')
  const [cache, setCache] = useState<Record<string, NotebookSummary[]>>({})
  const [loading, setLoading] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  /* 父组件内联传入加载函数；用 ref 取，避免每次渲染都重跑加载 effect */
  const loadRef = useRef(loadNotebooks)
  loadRef.current = loadNotebooks

  const courseIds = useMemo(() => courses.map((course) => course.id), [courses])
  const courseNames = useMemo(() => new Map(courses.map((course) => [course.id, course.name])), [courses])

  /* 打开时复位：默认落在当前课程、清空搜索、聚焦搜索框 */
  useEffect(() => {
    if (!open) return
    setCourseId(currentCourseId ?? '')
    setKeyword('')
    setCache((previous) => (currentCourseId ? { ...previous, [currentCourseId]: currentNotebooks } : previous))
    const timer = window.setTimeout(() => searchRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open, currentCourseId, currentNotebooks])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  /* 按需拉取 Notebook：选了哪门课就拉哪门课；「全部课程」则一次拉全。 */
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
        return [id, [] as NotebookSummary[]] as const
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

  const notebooks = useMemo(() => {
    const pool = courseId
      ? (courseId === currentCourseId ? currentNotebooks : (cache[courseId] ?? []))
      : courseIds.flatMap((id) => (id === currentCourseId ? currentNotebooks : (cache[id] ?? [])))
    const word = keyword.trim().toLowerCase()
    if (!word) return pool
    return pool.filter((notebook) => notebook.title.toLowerCase().includes(word))
  }, [courseId, courseIds, cache, currentCourseId, currentNotebooks, keyword])

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
        <h3>锁定一个 Notebook</h3>
        <p className="modal-hint">选好后，这一轮提问只围绕该 Notebook 正文及其资料作答。可以按课程筛选或搜索名称。</p>

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
              {loading && <p className="note-picker-empty">正在加载 Notebook…</p>}
          {!loading && notebooks.length === 0 && (
            <p className="note-picker-empty">
              {keyword.trim() ? '没有匹配的 Notebook，换个词试试' : '这里还没有 Notebook'}
            </p>
          )}
          {!loading && notebooks.map((notebook) => (
            <button
              key={notebook.id}
              type="button"
              className="note-picker-item"
              onClick={() => onPick(notebook)}
            >
              <span className="note-picker-title">{notebook.title}</span>
              {!courseId && <span className="note-picker-course">{courseNames.get(notebook.course_id) ?? ''}</span>}
            </button>
          ))}
        </div>

        <div className="modal-actions">
          <span className="note-picker-count">共 {notebooks.length} 本</span>
          <button className="ghost-button" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
