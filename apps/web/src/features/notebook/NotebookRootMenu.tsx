import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { NotebookSummary } from '../../types'
import { Dialog } from '../../components/Dialog'

export function NotebookRootMenu({ courseId, courseName, onClose, returnState }: { courseId: string; courseName: string; onClose: () => void; returnState?: unknown }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'create' | 'extend'>()
  const [title, setTitle] = useState('')
  const [books, setBooks] = useState<NotebookSummary[]>([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [booksLoading, setBooksLoading] = useState(false)
  const [booksError, setBooksError] = useState<string>()
  const [reload, setReload] = useState(0)
  useEffect(() => {
    if (mode !== 'extend') return
    let active = true
    setBooksLoading(true); setBooksError(undefined); setBooks([]); setSelected('')
    void api.listNotebooks(courseId).then(items => { if (active) { setBooks(items); setSelected(items[0]?.id ?? '') } }).catch((cause: unknown) => { if (active) setBooksError(cause instanceof Error ? cause.message : '目录读取失败') }).finally(() => { if (active) setBooksLoading(false) })
    return () => { active = false }
  }, [courseId, mode, reload])
  function upload(id: string) { navigate(`/courses/${courseId}/notebooks/${encodeURIComponent(id)}?upload=1`, { state: returnState }) }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (!title.trim() || busy) return
    setBusy(true); setError(undefined)
    try {
      upload((await api.createNotebook(courseId, title.trim())).id)
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : '笔记本创建失败') }
    finally { setBusy(false) }
  }
  return <Dialog title={courseName} label={`${courseName}笔记本操作`} description="新建一本笔记，或把下一讲放入已有笔记本。" onClose={onClose} busy={busy} closeLabel="关闭笔记本菜单">
    <div className="notebook-modes" role="group" aria-label="选择笔记本操作">
      <button type="button" className="notebook-mode-card" aria-label="新建笔记本" aria-pressed={mode === 'create'} disabled={busy} onClick={() => { setMode('create'); setError(undefined) }}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h13a1 1 0 0 1 1 1v15H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2ZM8 4v16M11 10h5M13.5 7.5v5" /></svg><span><strong>新建笔记本</strong><small>开始新的章节或主题</small></span>
      </button>
      <button type="button" className="notebook-mode-card" aria-label="扩充现有笔记本" aria-pressed={mode === 'extend'} disabled={busy} onClick={() => { setMode('extend'); setError(undefined) }}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5q4-2 9 1 5-3 9-1v14q-4-2-9 1-5-3-9-1ZM12 6v14M6 10h3M15 10h3M6 14h3M15 14h3" /></svg><span><strong>扩充现有笔记本</strong><small>接着整理下一讲资料</small></span>
      </button>
    </div>
    {mode === 'create' && <form className="botanical-dialog-form" onSubmit={event => void create(event)}>
      <label>笔记本名称<input autoFocus required value={title} maxLength={200} placeholder="例如：第一章 · 基础概念" disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="botanical-dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={!title.trim() || busy}>{busy ? '创建中…' : '创建并上传'}</button></div>
    </form>}
    {mode === 'extend' && <div className="botanical-dialog-form">
      {booksLoading ? <p className="dialog-inline-state" role="status">正在读取笔记本…</p> : booksError ? <div className="dialog-inline-state"><p className="form-error" role="alert">{booksError}</p><button type="button" className="secondary-button" onClick={() => setReload(value => value + 1)}>重新读取笔记本</button></div> : books.length ? <>
        <label>选择笔记本<select value={selected} onChange={event => setSelected(event.target.value)}>{books.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
        <div className="botanical-dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="button" className="primary-button" disabled={!selected} onClick={() => upload(selected)}>上传到此本</button></div>
      </> : <p className="dialog-inline-state">尚无笔记本，请选择新建笔记本。</p>}
    </div>}
  </Dialog>
}
