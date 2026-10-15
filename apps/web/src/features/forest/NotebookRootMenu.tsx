import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { NotebookSummary } from '../../types'

export function NotebookRootMenu({ courseId, courseName, onClose, returnState }: { courseId: string; courseName: string; onClose: () => void; returnState?: unknown }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'create' | 'extend'>()
  const [title, setTitle] = useState('')
  const [books, setBooks] = useState<NotebookSummary[]>([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const first = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    first.current?.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [])
  useEffect(() => {
    if (mode !== 'extend') return
    let active = true
    void api.listNotebooks(courseId).then(items => { if (active) { setBooks(items); setSelected(items[0]?.id ?? '') } }).catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '目录读取失败') })
    return () => { active = false }
  }, [courseId, mode])
  function upload(id: string) { navigate(`/courses/${courseId}/materials?notebook=${encodeURIComponent(id)}`, { state: returnState }) }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (!title.trim() || busy) return
    setBusy(true); setError(undefined)
    try { upload((await api.createNotebook(courseId, title.trim())).id) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '笔记本创建失败') }
    finally { setBusy(false) }
  }
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="course-gate-modal" role="dialog" aria-modal="true" aria-label={`${courseName}笔记本操作`} onKeyDown={event => {
      if (event.key === 'Escape' && !busy) { event.stopPropagation(); onClose() }
      if (event.key === 'Tab') {
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input,select'))
        const target = event.shiftKey ? controls.at(-1) : controls[0]
        if (document.activeElement === (event.shiftKey ? controls[0] : controls.at(-1))) { event.preventDefault(); target?.focus() }
      }
    }}>
      <button ref={first} className="modal-close" onClick={onClose} disabled={busy} aria-label="关闭笔记本菜单">×</button>
      <h2>{courseName}</h2><p>新建一本笔记，或把下一讲放入已有笔记本。</p>
      <div className="notebook-modes"><button onClick={() => { setMode('create'); setError(undefined) }}>新建笔记本</button><button onClick={() => { setMode('extend'); setError(undefined) }}>扩充现有笔记本</button></div>
      {mode === 'create' && <form onSubmit={event => void create(event)}><label>笔记本名称<input autoFocus value={title} maxLength={200} onChange={event => setTitle(event.target.value)} /></label><button className="primary-button" disabled={!title.trim() || busy}>创建并上传</button></form>}
      {mode === 'extend' && (books.length ? <><label>选择笔记本<select value={selected} onChange={event => setSelected(event.target.value)}>{books.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label><button className="primary-button" disabled={!selected} onClick={() => upload(selected)}>上传到此本</button></> : <p>尚无笔记本，请选择新建笔记本。</p>)}
      {error && <p role="alert">{error}</p>}
    </section>
  </div>
}
