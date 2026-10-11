import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import type { Notebook } from '../types'

export function NotesLibraryPage() {
  const { courses, coursesLoading } = useWorkspace()
  const [books, setBooks] = useState<Notebook[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [query, setQuery] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true); setError(undefined)
    void Promise.all(courses.map((course) => api.getNotebook(course.id)))
      .then((items) => { if (active) setBooks(items) })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '书架读取失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [courses])
  const visible = books.filter((book) => `${book.title} ${book.chapters.map((c) => c.title).join(' ')}`.includes(query.trim()))
  return <section className="notes-library page-enter">
    <header className="notes-library-heading"><div><h1>课程笔记本</h1><p>一门课一本书，每一讲都保留自己的内容。</p></div></header>
    <label className="notes-library-search"><span>⌕</span><input aria-label="搜索课程笔记本" placeholder="搜索课程或章节…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
    {error && <p role="alert">{error}</p>}
    {loading || coursesLoading ? <p role="status">正在读取书架…</p> : <div className="notes-bookshelf" aria-label="课程笔记本书架">
      <Link className="book-create-tile" to="/courses"><span>＋</span><strong>创建课程</strong><small>开始一本新的笔记本</small></Link>
      {visible.map((book, index) => <Link className={`note-book note-book-${index % 3}`} key={book.course_id} to={`/courses/${book.course_id}/notebook`} aria-label={`打开课程笔记本：${book.title}`}>
        <span className="note-book-spine" /><span className="note-book-content"><strong>{book.title}</strong><span className="note-book-rule" /><span className="note-book-course">{book.chapters.length} 章 · {book.chapters.reduce((n, c) => n + c.sections.length, 0)} 小节</span><small>{book.historical_sections.length ? `历史整理 ${book.historical_sections.length} 节` : '按讲次顺序阅读'}</small></span><span className="note-book-motif">♧</span>
      </Link>)}
    </div>}
    {!loading && !visible.length && <p className="notes-library-state">{query ? '没有匹配的课程笔记本。' : '创建课程并上传课件后，章节会出现在笔记本里。'}</p>}
  </section>
}
