import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useWorkspace } from '../components/AppLayout'
import type { Note, NotebookDocumentBlock, NotebookRead } from '../types'
import './NotebookPage.css'

type SaveState = 'saved' | 'unsaved' | 'saving' | 'error'

function newBlock(type: NotebookDocumentBlock['type'], text = ''): NotebookDocumentBlock {
  return { id: crypto.randomUUID(), type, text }
}

function BlockField({ block, onChange, onFocus, onEnter }: {
  block: NotebookDocumentBlock
  onChange: (text: string) => void
  onFocus: () => void
  onEnter: () => void
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (!ref.current) return
    ref.current.style.height = 'auto'
    ref.current.style.height = `${Math.max(ref.current.scrollHeight, block.type === 'p' ? 36 : 42)}px`
  }, [block.text, block.type])
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (block.type === 'h1' || block.type === 'h2' || event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      onEnter()
    }
  }
  return <textarea
    ref={ref}
    id={`notebook-block-${block.id}`}
    className={`notebook-document-block notebook-document-block-${block.type}`}
    rows={1}
    value={block.text}
    onChange={(event) => onChange(event.target.value)}
    onFocus={onFocus}
    onKeyDown={handleKeyDown}
    placeholder={block.type === 'h1' ? '章节标题' : block.type === 'h2' ? '小节标题' : block.type === 'bullet' ? '列表内容' : '写下你的笔记…'}
    aria-label={block.type === 'h1' ? '章节标题' : block.type === 'h2' ? '小节标题' : '笔记正文'}
    spellCheck
  />
}

export function NotebookPage() {
  const { courseId, notebookId } = useParams<{ courseId: string; notebookId: string }>()
  const [searchParams] = useSearchParams()
  const linkedSectionId = searchParams.get('section')
  const linkedChapterId = searchParams.get('chapter')
  const { course, materials, busy, uploadMaterial, refreshCurrentMaterials, setDocumentDirty } = useWorkspace()
  const [outline, setOutline] = useState<NotebookRead>()
  const [blocks, setBlocks] = useState<NotebookDocumentBlock[]>([])
  const [title, setTitle] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string>()
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [saveError, setSaveError] = useState<string>()
  const [uploadError, setUploadError] = useState<string>()
  const [titleError, setTitleError] = useState<string>()
  const [importing, setImporting] = useState(false)
  const [resourcesOpen, setResourcesOpen] = useState(true)
  const [directoryOpen, setDirectoryOpen] = useState(true)
  const [activeBlockId, setActiveBlockId] = useState<string>()
  const [titleSaving, setTitleSaving] = useState(false)
  const [linkedNote, setLinkedNote] = useState<Note>()
  const [linkedNoteError, setLinkedNoteError] = useState<string>()
  const fileInput = useRef<HTMLInputElement>(null)
  const savedRef = useRef('[]')
  const revisionRef = useRef(0)
  const blocksRef = useRef(blocks)
  const inFlightRef = useRef(false)
  const conflictRef = useRef(false)
  const failedRef = useRef(false)
  const saveNowRef = useRef<() => Promise<void>>(async () => {})
  const lastDeepLinkRef = useRef<string | undefined>(undefined)
  blocksRef.current = blocks

  useEffect(() => {
    if (!courseId || !notebookId) return
    let active = true
    setLoaded(false)
    setLoadError(undefined)
    setOutline(undefined)
    void Promise.all([api.getNotebookById(courseId, notebookId), api.getNotebookDocument(courseId, notebookId)])
      .then(([nextOutline, document]) => {
        if (!active) return
        setOutline(nextOutline)
        setTitle(nextOutline.title)
        setBlocks(document.blocks)
        savedRef.current = JSON.stringify(document.blocks)
        revisionRef.current = document.revision
        conflictRef.current = false
        failedRef.current = false
        setSaveState('saved')
        setSaveError(undefined)
        setLoaded(true)
      })
      .catch((cause: unknown) => { if (active) setLoadError(cause instanceof Error ? cause.message : '笔记读取失败') })
    return () => { active = false }
  }, [courseId, notebookId])

  useEffect(() => {
    if (!courseId || !notebookId || !linkedSectionId) { setLinkedNote(undefined); return }
    let active = true
    setLinkedNote(undefined)
    setLinkedNoteError(undefined)
    void api.getNote(linkedSectionId).then((note) => {
      if (!active) return
      if (note.course_id !== courseId || note.notebook_id !== notebookId) {
        setLinkedNoteError('这个小节不属于当前笔记。')
        return
      }
      setLinkedNote(note)
    }).catch((cause: unknown) => { if (active) setLinkedNoteError(cause instanceof Error ? cause.message : '小节读取失败') })
    return () => { active = false }
  }, [courseId, linkedSectionId, notebookId])

  const saveNow = useCallback(async () => {
    if (!courseId || !notebookId || !loaded || inFlightRef.current || conflictRef.current) return
    const snapshot = JSON.stringify(blocksRef.current)
    if (snapshot === savedRef.current) return
    inFlightRef.current = true
    setSaveState('saving')
    try {
      const saved = await api.saveNotebookDocument(courseId, notebookId, JSON.parse(snapshot) as NotebookDocumentBlock[], revisionRef.current)
      revisionRef.current = saved.revision
      savedRef.current = snapshot
      setSaveError(undefined)
      failedRef.current = false
      const stillDirty = JSON.stringify(blocksRef.current) !== snapshot
      setSaveState(stillDirty ? 'unsaved' : 'saved')
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) conflictRef.current = true
      failedRef.current = true
      setSaveError(cause instanceof Error ? cause.message : '笔记保存失败，请重试。')
      setSaveState('error')
    } finally {
      inFlightRef.current = false
      if (!failedRef.current && JSON.stringify(blocksRef.current) !== savedRef.current) {
        window.setTimeout(() => void saveNowRef.current(), 500)
      }
    }
  }, [courseId, notebookId, loaded])
  saveNowRef.current = saveNow

  useEffect(() => {
    if (!loaded) return
    const dirty = JSON.stringify(blocks) !== savedRef.current
    if (!dirty || conflictRef.current || failedRef.current) return
    setSaveState('unsaved')
    const timer = window.setTimeout(() => void saveNowRef.current(), 850)
    return () => window.clearTimeout(timer)
  }, [blocks, loaded])
  useEffect(() => {
    if (!loaded) return
    setDocumentDirty(JSON.stringify(blocks) !== savedRef.current || title !== outline?.title)
  }, [blocks, loaded, outline?.title, saveState, setDocumentDirty, title])
  useEffect(() => () => setDocumentDirty(false), [setDocumentDirty])

  const headings = useMemo(() => blocks.filter((block) => (block.type === 'h1' || block.type === 'h2') && block.text.trim()), [blocks])
  const bookMaterials = useMemo(() => materials.filter((material) => material.notebook_id === notebookId), [materials, notebookId])
  const hasExistingSections = Boolean(outline?.chapters.some((chapter) => chapter.sections.length) || outline?.historical_sections.length)
  const linkedBlockId = linkedNote ? `source-${linkedNote.id}` : undefined
  const linkedNoteInDocument = Boolean(linkedBlockId && blocks.some((block) => block.id === linkedBlockId))

  useEffect(() => {
    if (!loaded) return
    const targetId = linkedBlockId && blocks.some((block) => block.id === linkedBlockId)
      ? linkedBlockId
      : !linkedSectionId && linkedChapterId ? blocks.find((block) => block.type === 'h1' && block.text === outline?.chapters.find((chapter) => chapter.id === linkedChapterId)?.title)?.id : undefined
    if (!targetId) return
    const deepLinkKey = `${courseId}:${notebookId}:${linkedSectionId ?? linkedChapterId}:${targetId}`
    if (lastDeepLinkRef.current === deepLinkKey) return
    lastDeepLinkRef.current = deepLinkKey
    requestAnimationFrame(() => document.getElementById(`notebook-block-${targetId}`)?.scrollIntoView({ block: 'center' }))
  }, [blocks, courseId, linkedBlockId, linkedChapterId, linkedSectionId, loaded, notebookId, outline?.chapters])

  function addBlock(type: NotebookDocumentBlock['type'] = 'p', afterId?: string) {
    const block = newBlock(type)
    setBlocks((current) => {
      const index = afterId ? current.findIndex((item) => item.id === afterId) : -1
      const position = index >= 0 ? index + 1 : current.length
      return [...current.slice(0, position), block, ...current.slice(position)]
    })
    setActiveBlockId(block.id)
    requestAnimationFrame(() => document.getElementById(`notebook-block-${block.id}`)?.focus())
  }

  function updateBlock(id: string, value: Partial<NotebookDocumentBlock>) {
    setBlocks((current) => current.map((block) => block.id === id ? { ...block, ...value } : block))
  }

  async function renameTitle() {
    const nextTitle = title.trim()
    if (!courseId || !notebookId || !outline || !nextTitle || nextTitle === outline.title || titleSaving) {
      if (!nextTitle) setTitle(outline?.title ?? '')
      return
    }
    setTitleSaving(true)
    setTitleError(undefined)
    try {
      const renamed = await api.renameNotebook(courseId, notebookId, nextTitle)
      setOutline(renamed)
      setTitle(renamed.title)
    } catch (cause) {
      setTitleError(cause instanceof Error ? cause.message : '笔记名称保存失败')
    } finally { setTitleSaving(false) }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !courseId || !notebookId) return
    setUploadError(undefined)
    try {
      const lectureTitle = file.name.replace(/\.[^.]+$/, '').trim() || '新资料'
      await uploadMaterial(file, lectureTitle, '', false, notebookId)
      await refreshCurrentMaterials()
      setOutline(await api.getNotebookById(courseId, notebookId))
      setResourcesOpen(true)
    } catch (cause) { setUploadError(cause instanceof Error ? cause.message : '资料上传失败') }
  }

  async function importExistingNotes() {
    if (!courseId || !notebookId || !outline || importing || blocks.length) return
    setImporting(true)
    try {
      const chapters = await Promise.all(outline.chapters.filter((chapter) => chapter.sections.length).map(async (chapter) => ({
        title: chapter.title,
        notes: (await api.getNotebookChapter(courseId, notebookId, chapter.id)).sections,
      })))
      const imported = chapters.flatMap(({ title: chapterTitle, notes }) => [
        newBlock('h1', chapterTitle),
        ...notes.flatMap((note) => [{ ...newBlock('h2', note.title), id: `source-${note.id}` }, newBlock('p', note.content_markdown)]),
      ])
      if (outline.historical_sections.length) {
        const historical = await Promise.all(outline.historical_sections.map((section) => api.getNote(section.id)))
        imported.push(newBlock('h1', '历史笔记'), ...historical.flatMap((note) => [{ ...newBlock('h2', note.title), id: `source-${note.id}` }, newBlock('p', note.content_markdown)]))
      }
      setBlocks(imported)
      setActiveBlockId(imported[0]?.id)
    } catch (cause) { setSaveError(cause instanceof Error ? cause.message : '已有笔记导入失败') }
    finally { setImporting(false) }
  }

  if (!courseId || !notebookId) return <section className="route-state-card" role="alert">笔记地址无效。</section>
  if (loadError) return <section className="route-state-card" role="alert"><h1>无法打开笔记</h1><p>{loadError}</p><Link className="primary-button link-button" to="/courses">返回课程</Link></section>

  return <div className="notebook-document-page">
    <header className="notebook-document-topbar">
      <Link className="notebook-document-back" to="/courses" aria-label="返回课程">← <span>课程</span></Link>
      <span className="notebook-document-top-separator" aria-hidden="true" />
      <span className="notebook-document-top-course" title={course?.name}>{course?.name ?? '课程'}</span>
      <span className="notebook-document-top-chevron" aria-hidden="true">›</span>
      <strong className="notebook-document-top-title" title={outline?.title}>{outline?.title ?? '正在读取笔记…'}</strong>
      <div className="notebook-document-top-actions">
        <span className={`notebook-document-save-status notebook-document-save-${saveState}`} role="status">
          <span aria-hidden="true" />{titleSaving ? '名称保存中…' : saveState === 'saved' ? '已保存' : saveState === 'saving' ? '保存中…' : saveState === 'error' ? '保存失败' : '待保存'}
        </span>
        <details className="notebook-document-more"><summary>更多</summary><div><Link to={`/courses/${courseId}/materials?notebook=${notebookId}`}>管理课程资料</Link><button type="button" onClick={() => void saveNow()}>立即保存</button></div></details>
      </div>
    </header>
    <div className="notebook-document-workspace">
      <aside className="notebook-document-sidebar" aria-label="资料与目录">
        <div className="notebook-document-sidebar-heading">资料与目录</div>
        <input ref={fileInput} className="notebook-document-file-input" type="file" accept=".pptx,.pdf,.docx" onChange={(event) => void handleUpload(event)} aria-label="选择课程资料" />
        <button className="notebook-document-upload" type="button" disabled={busy} onClick={() => fileInput.current?.click()}><span aria-hidden="true">＋</span>{busy ? '上传中…' : '上传资料'}</button>
        {uploadError && <p className="notebook-document-sidebar-error" role="alert">{uploadError}</p>}
        <section className="notebook-document-sidebar-section">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={resourcesOpen} onClick={() => setResourcesOpen((value) => !value)}><span className={resourcesOpen ? 'is-open' : ''} aria-hidden="true">⌄</span>课程资料 <small>{bookMaterials.length}</small></button>
          {resourcesOpen && <div className="notebook-document-section-body">{bookMaterials.length ? bookMaterials.map((material) => <Link className="notebook-document-material" key={material.id} to={`/courses/${courseId}/materials?notebook=${notebookId}`} title={material.original_filename}><span className="notebook-document-file-icon" aria-hidden="true">≡</span><span><strong>{material.original_filename}</strong><small>{material.status === 'completed' ? `已整理 · ${material.page_count} 页` : material.status === 'failed' ? '处理失败' : '正在整理'}</small></span></Link>) : <p className="notebook-document-sidebar-empty">尚未上传资料</p>}</div>}
        </section>
        <section className="notebook-document-sidebar-section notebook-document-sidebar-directory">
          <button className="notebook-document-section-toggle" type="button" aria-expanded={directoryOpen} onClick={() => setDirectoryOpen((value) => !value)}><span className={directoryOpen ? 'is-open' : ''} aria-hidden="true">⌄</span>笔记目录 <small>随标题更新</small></button>
          {directoryOpen && <nav className="notebook-document-section-body" aria-label="笔记目录">{headings.length ? headings.map((heading) => <button className={`notebook-document-outline-item notebook-document-outline-${heading.type}${activeBlockId === heading.id ? ' is-active' : ''}`} key={heading.id} type="button" onClick={() => { document.getElementById(`notebook-block-${heading.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); setActiveBlockId(heading.id) }}>{heading.text}</button>) : <p className="notebook-document-sidebar-empty">正文标题会显示在这里</p>}</nav>}
        </section>
      </aside>
      <main className="notebook-document-canvas" aria-label="笔记正文">
        <div className="notebook-document-breadcrumb"><span>课程笔记</span><span aria-hidden="true">›</span><span>{course?.name ?? '课程'}</span><span aria-hidden="true">›</span><span>{outline?.title ?? '笔记'}</span></div>
        {!loaded ? <div className="notebook-document-loading" role="status">正在读取笔记正文…</div> : <article className="notebook-document-paper">
          <input className="notebook-document-title" value={title} onChange={(event) => setTitle(event.target.value)} onBlur={() => void renameTitle()} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} aria-label="笔记名称" maxLength={200} />
          <div className="notebook-document-meta">{course?.name ?? '课程'} · {bookMaterials.length} 份资料</div>
          {titleError && <p className="notebook-document-error" role="alert">{titleError}</p>}
          {saveError && <div className="notebook-document-error" role="alert">{saveError}{!conflictRef.current && <button type="button" onClick={() => { failedRef.current = false; setSaveError(undefined); void saveNow() }}>重试保存</button>}</div>}
          {linkedNoteError && <p className="notebook-document-error" role="alert">{linkedNoteError}</p>}
          {linkedNote && !linkedNoteInDocument && <section className="notebook-document-source-note" aria-label="来源小节"><div><strong>{linkedNote.title}</strong><span>来源小节</span></div><p>{linkedNote.content_markdown}</p><button type="button" onClick={() => { setBlocks((current) => [...current, { ...newBlock('h2', linkedNote.title), id: `source-${linkedNote.id}` }, newBlock('p', linkedNote.content_markdown)]); setDirectoryOpen(true) }}>加入当前笔记</button></section>}
          {!blocks.length && <div className="notebook-document-empty"><h2>开始写这篇笔记</h2><p>可以直接写正文，也可以添加标题。左侧目录会跟着标题变化。</p><div><button type="button" onClick={() => addBlock('p')}>写正文</button><button type="button" onClick={() => addBlock('h1')}>添加章节标题</button>{hasExistingSections && <button type="button" disabled={importing} onClick={() => void importExistingNotes()}>{importing ? '正在导入…' : '导入已有分节笔记'}</button>}</div></div>}
          {blocks.length > 0 && <div className="notebook-document-editor" aria-label="可编辑的笔记内容">{blocks.map((block) => <div className={`notebook-document-row${activeBlockId === block.id ? ' is-selected' : ''}`} key={block.id}>
            <div className="notebook-document-row-tools"><button type="button" title="在下方添加段落" aria-label="在下方添加段落" onClick={() => addBlock('p', block.id)}>＋</button></div>
            <BlockField block={block} onChange={(text) => updateBlock(block.id, { text })} onFocus={() => setActiveBlockId(block.id)} onEnter={() => addBlock('p', block.id)} />
            {activeBlockId === block.id && <div className="notebook-document-editbar" role="toolbar" aria-label="当前段落格式"><span>段落格式</span>{([['p', '正文'], ['h1', '章节标题'], ['h2', '小节标题'], ['bullet', '项目符号']] as const).map(([type, label]) => <button key={type} type="button" className={block.type === type ? 'is-active' : ''} onClick={() => updateBlock(block.id, { type })}>{label}</button>)}<button type="button" className="notebook-document-delete-block" disabled={blocks.length === 1} onClick={() => { setBlocks((current) => current.filter((item) => item.id !== block.id)); setActiveBlockId(undefined) }}>删除段落</button></div>}
          </div>)}</div>}
          {blocks.length > 0 && <button className="notebook-document-add-bottom" type="button" onClick={() => addBlock('p')}>＋ 添加段落</button>}
        </article>}
      </main>
    </div>
  </div>
}
