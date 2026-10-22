import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../../api'
import type { Course } from '../../types'

export type HomeSearchNote = Awaited<ReturnType<typeof api.searchForest>>[number]

export function HomeSearch({ courses, onCourse, onNote }: {
  courses: Course[]
  onCourse: (id: string) => void
  onNote: (note: HomeSearchNote) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const resultsId = useId()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<HomeSearchNote[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const text = query.trim()
  const matches = courses.filter(course => course.name.toLocaleLowerCase().includes(text.toLocaleLowerCase())).slice(0, 6)

  useEffect(() => {
    let active = true
    setResults([]); setError(undefined)
    if (!text) { setLoading(false); return }
    setLoading(true)
    const timer = setTimeout(() => {
      void api.searchForest(text).then(items => { if (active) setResults(items.slice(0, 8)) })
        .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '知识点搜索失败，请稍后重试') })
        .finally(() => { if (active) setLoading(false) })
    }, 250)
    return () => { active = false; clearTimeout(timer) }
  }, [text])

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented || document.querySelector('[aria-modal="true"]')) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); input.current?.focus(); setOpen(true)
      }
    }
    const dismiss = (event: PointerEvent) => { if (!host.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('keydown', shortcut)
    document.addEventListener('pointerdown', dismiss)
    return () => { document.removeEventListener('keydown', shortcut); document.removeEventListener('pointerdown', dismiss) }
  }, [])

  function choose(action: () => void) { setOpen(false); setQuery(''); action() }
  return <div className="home-search" ref={host} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); input.current?.focus(); setOpen(false) } }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
    <div className="home-search-field" role="search" aria-label="学习花园搜索">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
      <input ref={input} type="search" aria-label="搜索课程或知识点" placeholder="搜索课程或知识点" value={query} aria-controls={open && text ? resultsId : undefined} onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setOpen(true) }} />
      {text ? <button type="button" aria-label="清空搜索" onClick={() => { setQuery(''); input.current?.focus() }}>×</button> : <kbd aria-hidden="true">Ctrl K</kbd>}
    </div>
    {open && text && <section id={resultsId} className="home-search-results" aria-label="搜索结果">
      {matches.map(course => <button key={course.id} aria-label={`课程 ${course.name}`} onClick={() => choose(() => onCourse(course.id))}><span>课程</span><strong>{course.name}</strong></button>)}
      {results.map(note => <button key={note.note_id} onClick={() => choose(() => onNote(note))}><span>笔记</span><strong>{note.title}</strong><small>{note.course_name}</small></button>)}
      {loading && <p role="status">正在寻找知识点…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && !matches.length && !results.length && <p role="status">没有找到相关课程或知识点</p>}
    </section>}
  </div>
}
