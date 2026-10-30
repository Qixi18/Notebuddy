import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { UnboundNotebookSummary } from '../api/notebook'
import { useWorkspace } from '../components/AppLayout'
import { NotebookEditor, type NotebookEditorHandle } from '../features/notebook-editor/NotebookEditor'
import type { AIAction, SelectionAnchor } from '../features/notebook-editor/NotebookEditor'
import { useRegisterNotebookBridge, type NotebookBridgeValue } from '../features/notebook-editor/NotebookBridge'
import { countText, docToMarkdown, emptyDocument, excerptAroundSelection, extractOutline, normalizeDocument, stableStringify, type DocNode } from '../features/notebook-editor/document'
import { clearDraft, readDraft, type NotebookDraft } from '../features/notebook-editor/draftStore'
import { useNotebookSave } from '../features/notebook-editor/useNotebookSave'
import { historyOriginLabel, useHistoryDialog } from '../features/notebook-editor/historyDialog'
import { SourceUploadPanel } from '../features/notebook-workspace/SourceUploadPanel'
import type { NotebookRevision } from '../types'
import './NotebookPage.css'

export function UnboundNotebookPage() {
  const { notebookId } = useParams<{ notebookId: string }>()
  return <UnboundNotebookBody key={notebookId ?? ''} notebookId={notebookId} />
}

function UnboundNotebookBody({ notebookId }: { notebookId: string | undefined }) {
  const { conversationCourseId, setDocumentDirty } = useWorkspace()
  const [notebook, setNotebook] = useState<UnboundNotebookSummary>()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState<DocNode>(emptyDocument)
  const [loadError, setLoadError] = useState<string>()
  const [titleError, setTitleError] = useState<string>()
  const [imageError, setImageError] = useState<string>()
  const [draft, setDraft] = useState<NotebookDraft | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [selection, setSelection] = useState<SelectionAnchor | null>(null)
  const [editVersion, setEditVersion] = useState(0)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [conflictPreview, setConflictPreview] = useState<NotebookRevision | null>(null)
  const [notice, setNotice] = useState<string>()
  const editorRef = useRef<NotebookEditorHandle>(null)
  const save = useNotebookSave({ courseId: 'unbound', notebookId })
  const headings = useMemo(() => extractOutline(content), [content])
  const wordCount = useMemo(() => countText(content), [content])

  const insertAI = useCallback((text: string, mode: 'after' | 'replace', anchor: SelectionAnchor | null, expectedRevision?: number, expectedEditVersion?: number) => {
    const handle = editorRef.current
    const editor = handle?.editor
    if (!handle || !editor || (expectedRevision !== undefined && expectedRevision !== save.revision)
      || (expectedEditVersion !== undefined && expectedEditVersion !== editVersion) || !anchor) return false
    if (mode === 'replace') {
      if (!anchor.text.trim() || editor.state.doc.textBetween(anchor.from, anchor.to, '\n') !== anchor.text) return false
      return handle.replaceRange(text, anchor.from, anchor.to)
    }
    if (anchor.to > editor.state.doc.content.size || editor.state.doc.textBetween(anchor.from, anchor.to, '\n') !== anchor.text) return false
    handle.insertMarkdown(text, anchor.to)
    return true
  }, [editVersion, save.revision])

  const adoptDocument = useCallback((document: DocNode, revision: number, updatedAt: string, expectedEditVersion: number) => {
    if (editVersion !== expectedEditVersion || save.isDirty() || save.revision !== revision - 1) return false
    const normalized = normalizeDocument(document)
    editorRef.current?.replaceContent(normalized)
    setContent(normalized)
    setEditVersion((value) => value + 1)
    save.reset(normalized, revision, updatedAt)
    return true
  }, [editVersion, save.isDirty, save.reset, save.revision])

  const bridgeValue = useMemo<NotebookBridgeValue | null>(() => notebookId && notebook ? {
    courseId: null, notebookId, title, revision: save.revision, editVersion,
    excerpt: excerptAroundSelection(content, selection?.text), selection, insertAI,
    isDirty: save.isDirty, adoptDocument,
  } : null, [adoptDocument, content, conversationCourseId, editVersion, insertAI, notebook, notebookId, save.isDirty, save.revision, selection, title])
  useRegisterNotebookBridge(bridgeValue)

  useEffect(() => {
    if (!notebookId) return
    let active = true
    setNotebook(undefined)
    setLoadError(undefined)
    void Promise.all([api.getUnboundNotebook(notebookId), api.getUnboundNotebookDocument(notebookId)])
      .then(async ([book, document]) => {
        if (!active) return
        const normalized = normalizeDocument(document.content)
        setNotebook(book)
        setTitle(book.title)
        setContent(normalized)
        save.reset(normalized, document.revision, document.updated_at)
        setEditVersion(0)
        const local = await readDraft('unbound', notebookId)
        if (active && local && stableStringify(local.content) !== stableStringify(normalized)) setDraft(local)
      })
      .catch((cause: unknown) => { if (active) setLoadError(cause instanceof Error ? cause.message : '笔记读取失败') })
    return () => { active = false }
    // Keep the editor mounted for this notebook only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebookId])

  useEffect(() => {
    setDocumentDirty(Boolean(notebook && (save.state !== 'saved' || title !== notebook.title)))
    return () => setDocumentDirty(false)
  }, [notebook, save.state, setDocumentDirty, title])

  async function rename() {
    if (!notebookId || !notebook || renaming || title.trim() === notebook.title) return
    if (!title.trim()) { setTitleError('笔记名称不能为空'); return }
    setRenaming(true)
    setTitleError(undefined)
    try {
      const updated = await api.renameUnboundNotebook(notebookId, title.trim())
      setNotebook(updated)
      setTitle(updated.title)
    } catch (cause) {
      setTitleError(cause instanceof Error ? cause.message : '名称保存失败')
    } finally { setRenaming(false) }
  }

  async function refreshAfterGeneration() {
    if (!notebookId) return
    if (save.isDirty()) {
      setNotice('讲解已写入服务器，但你有未保存的编辑；已保留本地内容，保存后再刷新可看到生成结果。')
      return
    }
    try {
      const document = await api.getUnboundNotebookDocument(notebookId)
      const next = normalizeDocument(document.content)
      editorRef.current?.replaceContent(next)
      setContent(next)
      setEditVersion((version) => version + 1)
      save.reset(next, document.revision, document.updated_at)
      setNotice('资料解析与讲解已写入正文。')
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '生成结果刷新失败')
    }
  }

  function restoreDraft() {
    if (!draft) return
    const restored = normalizeDocument(draft.content)
    editorRef.current?.replaceContent(restored)
    setContent(restored)
    setEditVersion((version) => version + 1)
    save.markEdited(restored)
    setDraft(null)
  }

  async function uploadImage(file: File): Promise<{ src: string; attachmentId: string } | null> {
    if (!notebookId) return null
    setImageError(undefined)
    try {
      const attachment = await api.uploadUnboundNotebookAttachment(notebookId, file)
      return { src: attachment.url, attachmentId: attachment.id }
    } catch (cause) {
      setImageError(cause instanceof Error ? cause.message : '图片上传失败')
      return null
    }
  }

  function openAssistant(action?: AIAction) {
    window.dispatchEvent(new CustomEvent('notebuddy:open-assistant', {
      detail: { courseId: conversationCourseId, notebookId, action, selection, revision: save.revision, title },
    }))
  }

  function exportMarkdown() {
    const url = URL.createObjectURL(new Blob([docToMarkdown(content)], { type: 'text/markdown;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${title.trim() || '笔记'}.md`
    anchor.click()
    URL.revokeObjectURL(url)
    setNotice('已导出 Markdown。')
  }

  function exportPdf() {
    const html = editorRef.current?.editor?.getHTML()
    if (!html) return
    const win = window.open('', '_blank')
    if (!win) { setNotice('浏览器阻止了打印窗口，请允许弹窗后重试。'); return }
    const styles = Array.from(document.querySelectorAll('link[rel="stylesheet"], style')).map((node) => node.outerHTML).join('')
    const safeTitle = title.replace(/[&<>\"]/g, '')
    win.document.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><title>${safeTitle}</title>${styles}<style>body{color:#24322a;font-family:var(--nb-sans,sans-serif)}article{max-width:760px;margin:0 auto;padding:40px 24px}img{max-width:100%}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dbe4dc;padding:6px 8px}@media print{article{padding:0}}</style></head><body><article class="ProseMirror">${html}</article></body></html>`)
    win.document.close()
    win.setTimeout(() => { win.focus(); win.print() }, 450)
  }

  async function showServerVersion() {
    const server = await save.fetchServer()
    if (server) setConflictPreview({ revision: server.revision, origin: 'autosave', created_at: server.updated_at, schema_version: 2, content: server.content })
  }

  async function useServerVersion() {
    if (!conflictPreview) return
    const latest = normalizeDocument(conflictPreview.content)
    editorRef.current?.replaceContent(latest)
    setContent(latest)
    setEditVersion((version) => version + 1)
    const server = await save.fetchServer()
    if (server) save.applyServer({ ...server, content: latest })
    save.setConflictOpen(false)
    setConflictPreview(null)
  }

  async function restoreRevision(revision: number) {
    if (!notebookId || !window.confirm(`恢复 revision ${revision}？当前版本会保留在历史中。`)) return
    if (save.isDirty() && !await save.saveNow()) return
    const restored = await api.restoreUnboundNotebookRevision(notebookId, revision, save.getRevision())
    const next = normalizeDocument(restored.content)
    editorRef.current?.replaceContent(next)
    setContent(next)
    setEditVersion((version) => version + 1)
    save.reset(next, restored.revision, restored.updated_at)
    setHistoryOpen(false)
    setNotice('已恢复历史版本。')
  }

  if (!notebookId) return <section className="route-state-card" role="alert">笔记地址无效。</section>
  if (loadError) return <section className="route-state-card" role="alert"><h1>无法打开笔记</h1><p>{loadError}</p><Link className="primary-button link-button" to="/courses">返回课程</Link></section>

  const saveLabel = save.state === 'conflict' ? '有冲突' : save.state === 'error' || titleError ? '保存失败'
    : save.state === 'saving' || renaming ? '保存中…'
      : save.state === 'unsaved' || title !== (notebook?.title ?? '') ? '待保存' : '已保存'

  return <div className="notebook-document-page">
    <header className="notebook-document-topbar">
      <Link className="notebook-document-back" to="/courses" aria-label="返回课程">← <span>课程</span></Link>
      <span className="notebook-document-top-separator" aria-hidden="true" />
      <span className="notebook-document-top-course">未分类</span>
      <span className="notebook-document-top-chevron" aria-hidden="true">›</span>
      <strong className="notebook-document-top-title" title={notebook?.title}>{notebook?.title ?? '正在读取笔记…'}</strong>
      <div className="notebook-document-top-actions">
        <span className={`notebook-document-save-status notebook-document-save-${save.state}`} role="status" aria-live="polite">{saveLabel}</span>
        <div className="notebook-document-history-actions" role="group" aria-label="撤销与重做">
          <button type="button" onClick={() => editorRef.current?.undo()} aria-label="撤销">↶</button>
          <button type="button" onClick={() => editorRef.current?.redo()} aria-label="重做">↷</button>
        </div>
        <button className="notebook-document-ai-button" type="button" onClick={() => openAssistant()} disabled={!conversationCourseId} aria-label="打开 AI 助手"><span aria-hidden="true">✦</span> AI 助手</button>
        <details className="notebook-document-more">
          <summary aria-label="更多操作">更多</summary>
          <div>
            <button type="button" onClick={() => void save.saveNow()}>立即保存</button>
            <button type="button" onClick={() => setHistoryOpen(true)}>历史版本</button>
            <button type="button" onClick={exportMarkdown}>导出 Markdown</button>
            <button type="button" onClick={exportPdf}>导出 PDF</button>
            <button type="button" onClick={() => void navigator.clipboard.writeText(window.location.href).then(() => setNotice('链接已复制。'))}>复制链接</button>
          </div>
        </details>
      </div>
    </header>
    {notice && <div className="notebook-document-notice" role="status">{notice}<button type="button" onClick={() => setNotice(undefined)} aria-label="关闭提示">×</button></div>}
    {save.error && <div className="notebook-document-banner is-error" role="alert">
      <span>{save.error}</span>
      {save.state === 'conflict' ? <div>
        <button type="button" onClick={() => void showServerVersion()}>查看服务器版本</button>
        <button type="button" onClick={() => void save.overwriteServer()}>用当前内容覆盖</button>
      </div> : <button type="button" onClick={() => save.retry()}>重试保存</button>}
    </div>}
    {draft && <div className="notebook-document-banner" role="status">发现本地草稿。
      <button type="button" onClick={restoreDraft}>恢复草稿</button>
      <button type="button" onClick={() => { setDraft(null); void clearDraft('unbound', notebookId) }}>忽略</button>
    </div>}
    {imageError && <div className="notebook-document-banner is-error" role="alert">{imageError}<button type="button" onClick={() => setImageError(undefined)}>关闭</button></div>}
    <div className="notebook-document-workspace">
      <aside className="notebook-document-sidebar" aria-label="笔记目录">
        <div className="notebook-document-sidebar-heading">资料与目录</div>
        <SourceUploadPanel notebookId={notebookId} onDocumentUpdated={() => void refreshAfterGeneration()} />
        <nav className="notebook-document-section-body" aria-label="笔记目录">
          {headings.length ? headings.map((heading) => <button className={`notebook-document-outline-item notebook-document-outline-h${heading.level}`} key={heading.id} type="button" onClick={() => editorRef.current?.focusBlock(heading.id)}>{heading.text}</button>) : <p className="notebook-document-sidebar-empty">正文标题会显示在这里</p>}
        </nav>
      </aside>
      <main className="notebook-document-canvas" aria-label="笔记正文">
        {!notebook ? <div className="notebook-document-loading" role="status">正在读取笔记正文…</div> : <article className="notebook-document-paper">
          <input className="notebook-document-title" value={title} onChange={(event) => { setTitle(event.target.value); setTitleError(undefined) }} onBlur={() => void rename()} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} aria-label="笔记名称" maxLength={200} />
          <div className="notebook-document-meta"><span>未分类 · 约 {wordCount.toLocaleString('zh-CN')} 字</span>{save.lastSavedAt && <span>最后编辑 {new Date(save.lastSavedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>}</div>
          {titleError && <p className="notebook-document-error" role="alert">{titleError}</p>}
          <NotebookEditor
            ref={editorRef}
            initialContent={content}
            onChange={(next) => { setContent(next); setEditVersion((version) => version + 1); save.markEdited(next) }}
            onSelectionChange={setSelection}
            onRequestAI={conversationCourseId ? (action) => openAssistant(action) : undefined}
            onSaveShortcut={() => void save.saveNow()}
            onUploadImage={uploadImage}
            onReady={(editor) => save.reset(editor.getJSON() as DocNode, save.revision, save.lastSavedAt)}
          />
        </article>}
      </main>
    </div>
    {save.conflictOpen && <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="保存冲突"><div className="nb-modal"><h2>这篇笔记已在别处更新</h2><p>本地修改仍然保留，选择要继续使用的版本。</p><div className="nb-modal-actions is-stacked"><button type="button" onClick={() => void showServerVersion()}>查看服务器版本</button><button type="button" onClick={() => save.keepLocalDraft()}>保留本地草稿并暂停自动保存</button><button type="button" className="is-danger" onClick={() => void save.overwriteServer()}>用本地版本覆盖服务器</button><button type="button" className="primary-button" onClick={() => save.setConflictOpen(false)}>继续编辑</button></div></div></div>}
    {conflictPreview && <div className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="服务器版本预览"><div className="nb-modal is-wide"><h2>服务器上的最新版本</h2><pre className="notebook-document-conflict-preview">{docToMarkdown(conflictPreview.content).slice(0, 12000)}</pre><div className="nb-modal-actions"><button type="button" onClick={() => setConflictPreview(null)}>返回</button><button type="button" className="primary-button" onClick={() => void useServerVersion()}>使用服务器版本</button></div></div></div>}
    {historyOpen && <UnboundHistoryPanel notebookId={notebookId} onClose={() => setHistoryOpen(false)} onRestore={restoreRevision} />}
  </div>
}

function UnboundHistoryPanel({ notebookId, onClose, onRestore }: { notebookId: string; onClose: () => void; onRestore: (revision: number) => Promise<void> }) {
  const [items, setItems] = useState<Array<{ revision: number; origin: string; created_at: string }>>([])
  const [preview, setPreview] = useState<DocNode | null>(null)
  const [selected, setSelected] = useState<number>()
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const dialogRef = useHistoryDialog(onClose, busy)
  useEffect(() => {
    let active = true
    void api.listUnboundNotebookRevisions(notebookId).then((rows) => { if (active) setItems(rows) })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '历史版本读取失败') })
    return () => { active = false }
  }, [notebookId])
  async function selectRevision(revision: number) {
    if (busy) return
    setSelected(revision)
    setBusy(true)
    try { setPreview((await api.getUnboundNotebookRevision(notebookId, revision)).content) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '版本内容读取失败') }
    finally { setBusy(false) }
  }
  async function restore() {
    if (selected === undefined || busy) return
    setBusy(true)
    setError(undefined)
    try { await onRestore(selected) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '恢复失败') }
    finally { setBusy(false) }
  }
  return <div ref={dialogRef} className="nb-modal-backdrop" role="dialog" aria-modal="true" aria-label="历史版本" aria-busy={busy} tabIndex={-1}><div className="nb-modal is-wide">
    <div className="nb-modal-head"><h2>历史版本</h2><button type="button" onClick={onClose} disabled={busy} aria-label="关闭">×</button></div>
    {error && <p className="notebook-document-error" role="alert">{error}</p>}
    <div className="notebook-document-history"><div className="notebook-document-history-list">{items.length ? items.map((item) => <button key={item.revision} type="button" disabled={busy} className={selected === item.revision ? 'is-active' : ''} onClick={() => void selectRevision(item.revision)}><strong>revision {item.revision}</strong><span>{new Date(item.created_at).toLocaleString('zh-CN')}</span><small>{historyOriginLabel(item.origin)}</small></button>) : <p className="notebook-document-sidebar-empty">还没有历史快照。</p>}</div><div className="notebook-document-history-preview">{preview ? <pre>{docToMarkdown(preview).slice(0, 20000)}</pre> : <p>选择左侧版本查看内容。</p>}</div></div>
    <div className="nb-modal-actions"><button type="button" onClick={onClose} disabled={busy}>关闭</button><button type="button" className="primary-button" disabled={selected === undefined || busy} onClick={() => void restore()}>恢复到此版本</button></div>
  </div></div>
}
