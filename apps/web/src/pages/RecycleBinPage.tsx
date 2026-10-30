import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Course } from '../types'
import type { DeletedNotebookSummary } from '../api/courses'

type Target = { kind: 'course' | 'notebook'; id: string }
const date = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '时间未知'

export function RecycleBinPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [notebooks, setNotebooks] = useState<DeletedNotebookSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState<string>()

  async function load() {
    setLoading(true)
    setError(undefined)
    try {
      const [nextCourses, nextNotebooks] = await Promise.all([api.listDeletedCourses(), api.listDeletedNotebooks()])
      setCourses(nextCourses)
      setNotebooks(nextNotebooks)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '读取失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  async function restore(kind: Target['kind'], id: string, courseId?: string | null) {
    if (busy) return
    setBusy(id)
    try {
      if (kind === 'course') await api.restoreCourse(id)
      else await api.restoreDeletedNotebook(id, courseId ?? null)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '恢复失败') }
    finally { setBusy(undefined) }
  }

  async function purge(item: Target) {
    if (busy) return
    setBusy(item.id)
    try {
      if (item.kind === 'course') await api.permanentlyDeleteCourse(item.id)
      else await api.permanentlyDeleteNotebook(item.id)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '彻底删除失败') }
    finally { setBusy(undefined) }
  }

  const actions = (item: Target, courseId?: string | null) => <div className="recycle-actions">
    <button type="button" className="recycle-restore" disabled={Boolean(busy)} onClick={() => void restore(item.kind, item.id, courseId)}>{busy === item.id ? '处理中…' : '恢复'}</button>
    <button type="button" className="recycle-purge" disabled={Boolean(busy)} onClick={() => void purge(item)}>彻底删除</button>
  </div>

  return <main className="recycle-page page-enter" aria-labelledby="recycle-title">
    <header className="recycle-heading"><div><span className="recycle-eyebrow">已移除内容</span><h1 id="recycle-title">回收站</h1><p>恢复误删的内容，或清除不再需要的项目。</p></div><Link className="secondary-button link-button" to="/courses">返回课程</Link></header>
    <div className="recycle-overview" aria-live="polite"><div><strong>{courses.length}</strong><span>门课程</span></div><div><strong>{notebooks.length}</strong><span>篇笔记</span></div><p>彻底删除无法撤销。删除课程不会同时删除已独立存放的笔记。</p></div>
    {error && <div className="recycle-error" role="alert">{error}<button type="button" onClick={() => void load()}>重新读取</button></div>}
    {loading ? <p className="recycle-state" role="status">正在读取回收站…</p> : courses.length === 0 && notebooks.length === 0 ? <div className="recycle-empty"><span aria-hidden="true">✓</span><h2>回收站是空的</h2><p>移除的课程和笔记会显示在这里。</p></div> : <>
      <section className="recycle-section" aria-labelledby="recycle-courses-title"><div className="recycle-section-heading"><div><h2 id="recycle-courses-title">课程</h2><p>已移除的课程可单独恢复</p></div><span>{courses.length}</span></div>{courses.length ? <div className="recycle-list">{courses.map(course => <article className="recycle-row" key={course.id}><span className="recycle-item-icon" aria-hidden="true">▦</span><div className="recycle-item-copy"><h3>{course.name}</h3><p>删除于 {date(course.deleted_at)}</p></div>{actions({ kind: 'course', id: course.id })}</article>)}</div> : <p className="recycle-section-empty">没有已删除的课程</p>}</section>
      <section className="recycle-section" aria-labelledby="recycle-notebooks-title"><div className="recycle-section-heading"><div><h2 id="recycle-notebooks-title">笔记</h2><p>恢复后可继续编辑和查看关联资料</p></div><span>{notebooks.length}</span></div>{notebooks.length ? <div className="recycle-list">{notebooks.map(book => <article className="recycle-row" key={book.id}><span className="recycle-item-icon" aria-hidden="true">▤</span><div className="recycle-item-copy"><h3>{book.title}</h3><p>{book.course_id ? '课程笔记' : '未分类笔记'} · 删除于 {date(book.deleted_at)}</p></div>{actions({ kind: 'notebook', id: book.id }, book.course_id)}</article>)}</div> : <p className="recycle-section-empty">没有已删除的笔记</p>}</section>
    </>}
  </main>
}
