import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useWorkspace } from '../components/AppLayout'
import { adjacentSection, notebookPath, resolveSection } from '../features/notebook/navigation'
import type { NotebookRead, NotebookSection, NotebookReadingPosition } from '../types'
import { NoteSectionReader } from './NotesPage'
import { useReadingPosition } from '../features/notebook/useReadingPosition'
import { NotebookRootMenu } from '../features/forest/NotebookRootMenu'

export function NotebookPage() {
  const { courseId = '', notebookId = '' } = useParams()
  const [query] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const forestReturn = (location.state as { fromForest?: boolean; forestReturn?: string } | null)?.fromForest ? (location.state as { forestReturn?: string }).forestReturn ?? '/forest' : undefined
  const { notes, materials, job, upsertNotes, setSelectedNoteId, courseContentLoading, noteDirty } = useWorkspace()
  const [outline, setOutline] = useState<NotebookRead>()
  const bookmarkKey = `${courseId}:${notebookId}`
  const [bookmarkState, setBookmarkState] = useState<{ key: string; value: NotebookReadingPosition | null }>()
  const bookmark = bookmarkState?.key === bookmarkKey ? bookmarkState.value : undefined
  const setBookmark = (value: NotebookReadingPosition | null | undefined) => setBookmarkState(value === undefined ? undefined : { key: bookmarkKey, value })
  const [resumeOffset, setResumeOffset] = useState(0)
  const [resumeMessage, setResumeMessage] = useState<string>()
  const [rootOpen, setRootOpen] = useState(false)
  const contentRef = useRef<HTMLElement>(null)
  const initialQuery = useRef(query.toString())
  const resumeTarget = useRef<string | undefined>(undefined)
  const returnState = location.state as { sceneReturn?: string; sceneEntry?: string } | null
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)
  const [reading, setReading] = useState(false)
  const [ordering, setOrdering] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const mode = query.get('mode') === 'book' ? 'book' : 'chapter'
  const chapterParam = query.get('chapter') ?? undefined
  const sectionParam = query.get('section') ?? undefined
  const bookMatches = outline?.id === notebookId && (!bookmark || bookmark.notebook_id === notebookId)
  const selected = !bookMatches || query.has('directory') || resumeMessage && !sectionParam && !chapterParam ? undefined : outline && resolveSection(outline, chapterParam, sectionParam)
  const chapter = outline && [...outline.chapters, ...outline.removed_chapters].find((c) => c.id === (selected?.material_id ?? chapterParam))
  const directSectionId = (!selected?.material_id || chapter?.deleted_at) ? selected?.id : undefined
  const materialState = materials.map((m) => `${m.id}:${m.status}:${m.chapter_order}`).join('|')

  useEffect(() => {
    setOutline(undefined); setBookmark(undefined); setLoading(true); setError(undefined); setResumeMessage(undefined); setResumeOffset(0); initialQuery.current = query.toString()
  }, [courseId, notebookId])

  useEffect(() => {
    let active = true
    async function loadOutline() {
      const book = notebookId ? await api.getNotebookById(courseId, notebookId) : await api.getNotebook(courseId) as NotebookRead
      if (!active) return
      if (!notebookId) {
        // Legacy chapter/section URLs resolve actual ownership, not only the default book.
        if (sectionParam) {
          const note = await api.getNote(sectionParam)
          if (note.course_id !== courseId || !note.notebook_id) throw new Error('没有找到本课程的小节归属。')
          navigate(notebookPath(courseId, note, mode), { replace: true, state: location.state }); return
        }
        if (chapterParam && chapterParam !== 'history') {
          const tree = await api.getCourseTree(courseId)
          const owner = tree.notebooks.find(item => [...item.chapters, ...item.removed_chapters].some(ch => ch.id === chapterParam))
          if (!owner) throw new Error('没有找到本课程的章节。')
          navigate(`/courses/${courseId}/notebooks/${owner.id}?${query}`, { replace: true, state: location.state }); return
        }
        navigate(`/courses/${courseId}/notebooks/${book.id}${query.size ? `?${query}` : ''}`, { replace: true, state: location.state }); return
      }
      setOutline(book)
      if (bookmark === undefined) {
        const saved = await api.getReadingPosition(courseId, notebookId)
        if (!active) return
        setBookmark(saved)
        if (!initialQuery.current && saved) {
          const valid = saved.notebook_id === notebookId && (saved.mode === 'book' || saved.mode === 'chapter') && Number.isFinite(saved.section_offset) && saved.section_offset >= 0 && saved.section_offset <= 1
          const section = valid && saved.note_id ? resolveSection(book, saved.chapter_id ?? 'history', saved.note_id) : undefined
          if (!valid || (saved.note_id && !section) || (saved.chapter_id && !saved.note_id && !book.chapters.some(ch => ch.id === saved.chapter_id))) {
            setResumeMessage('上次阅读位置已失效；请从这本笔记的目录重新选择。')
            navigate(`/courses/${courseId}/notebooks/${notebookId}?directory=1`, { replace: true, state: location.state })
          } else {
            setResumeOffset(saved.section_offset)
            const path = notebookPath(courseId, section, saved.mode, notebookId)
            resumeTarget.current = path
            navigate(path, { replace: true, state: location.state })
          }
        }
      }
    }
    void loadOutline().catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '目录读取失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [courseId, notebookId, materialState, job?.id, job?.status, reloadToken])
  useEffect(() => {
    if (!outline || outline.id !== notebookId || courseContentLoading || bookmark === undefined || bookmark && bookmark.notebook_id !== notebookId) return
    let active = true
    setReading(true); setError(undefined)
    async function load() {
      const chapters = mode === 'book' ? outline!.chapters : chapter && !chapter.deleted_at ? [chapter] : []
      for (const item of chapters) {
        const content = await api.getNotebookChapter(courseId, notebookId, item.id)
        if (!active) return
        upsertNotes(content.sections)
      }
      const directSections = mode === 'book' ? [...outline!.historical_sections] : selected?.material_id === null ? [selected] : []
      if (chapter?.deleted_at) directSections.push(...chapter.sections)
      for (const section of directSections) {
        const note = await api.getNote(section.id)
        if (!active) return
        if (active && note.course_id === courseId && note.notebook_id === notebookId) upsertNotes([note])
      }
    }
    void load().catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : '章节读取失败') })
      .finally(() => { if (active) setReading(false) })
    return () => { active = false }
  }, [courseId, notebookId, outline, chapter?.id, mode, directSectionId, courseContentLoading, upsertNotes, bookmark])

  useEffect(() => {
    if (!selected || courseContentLoading || !notes.some((n) => n.id === selected.id)) return
    setSelectedNoteId(selected.id)
  }, [selected?.id, sectionParam, reading, courseContentLoading, notes, setSelectedNoteId])

  function open(section: NotebookSection) { navigate(notebookPath(courseId, section, mode, notebookId), { state: location.state }) }
  async function moveChapter(index: number, direction: number) {
    if (!outline || ordering || noteDirty) return
    const ids = outline.chapters.map((c) => c.id)
    ;[ids[index], ids[index + direction]] = [ids[index + direction], ids[index]]
    setOrdering(true)
    try { setOutline(await api.reorderNotebookChapters(courseId, notebookId, ids, outline.order_revision)) }
    catch (cause) {
      setError(cause instanceof Error ? cause.message : '排序失败')
      try { setOutline(await api.getNotebookById(courseId, notebookId)) } catch { /* Keep last readable outline. */ }
    } finally { setOrdering(false) }
  }

  const progress = useReadingPosition(courseId, notebookId, bookMatches ? bookmark : undefined, selected, mode, bookMatches && !loading && !reading && !courseContentLoading && bookmark !== undefined && Boolean(selected && notes.some(note => note.id === selected.id)), location.pathname + location.search, resumeTarget.current === location.pathname + location.search ? resumeOffset : 0, contentRef)
  const uploadPath = `/courses/${courseId}/materials?notebook=${notebookId}`

  if (loading || outline && !bookMatches) return <p role="status">正在读取课程目录…</p>
  if (!outline) return <div><button onClick={() => setRootOpen(true)}>新建笔记本</button>{rootOpen && <NotebookRootMenu courseId={courseId} courseName={'当前课程'} onClose={() => setRootOpen(false)} />}<p role="alert">{error ?? '笔记本读取失败'}</p></div>
  const previous = selected && adjacentSection(outline, selected.id, -1)
  const next = selected && adjacentSection(outline, selected.id, 1)
  const visibleChapters = mode === 'book' ? [...outline.chapters, ...(chapter?.deleted_at ? [chapter] : [])] : chapter ? [chapter] : []
  const visibleHistory = mode === 'book' ? outline.historical_sections : selected?.material_id === null ? [selected] : []
  function renderSection(section: NotebookSection) {
    const note = notes.find((n) => n.id === section.id)
    return <article id={`section-${section.id}`} className="notebook-section" data-note={section.id} data-chapter={section.material_id ?? ''} key={section.id}>
      {selected?.id === section.id && note ? <NoteSectionReader noteId={section.id} /> : <><header><h3>{section.title}</h3><button className="text-button" onClick={() => open(section)}>定位与编辑此小节</button></header>{note ? <div className="markdown-preview"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{note.content_markdown}</ReactMarkdown></div> : <p role="status">{reading ? '正在读取…' : '正文暂未载入，请重试。'}</p>}</>}
    </article>
  }
  return <div className="notebook-page page-enter">
    {returnState?.sceneReturn && <Link className="notebook-forest-return" to={returnState.sceneReturn} state={{ restoreSceneEntry: returnState.sceneEntry }}>❧ 返回课程树</Link>}
    {forestReturn && <Link className="notebook-forest-return" to={forestReturn}>❧ 返回知识森林</Link>}
    <header className="notebook-header"><div><Link to="/notes">← 课程书架</Link><h1>{outline.title}</h1><p>{outline.chapters.length} 章 · 按讲次阅读与积累</p></div><div className="notebook-modes" role="group" aria-label="阅读模式"><button className={mode === 'chapter' ? 'primary-button' : 'secondary-button'} onClick={() => navigate(notebookPath(courseId, selected, undefined, notebookId), { state: location.state })}>章节阅读</button><button className={mode === 'book' ? 'primary-button' : 'secondary-button'} onClick={() => navigate(notebookPath(courseId, selected, 'book', notebookId), { state: location.state })}>整本阅读</button></div></header>
    {error && <p role="alert" className="form-error">{error}<button onClick={() => { setLoading(true); setReloadToken(current => current + 1) }}>重新读取目录与书签</button></p>}
    {resumeMessage && <p role="alert">{resumeMessage}</p>}
    {progress.error && <p role="alert">{progress.error}<button onClick={() => void progress.retry()}>重试保存当前位置</button></p>}
    <div className="notebook-layout"><nav className="notebook-outline" aria-label="笔记本目录"><h2>目录</h2>
      {outline.chapters.map((item, index) => <div className="notebook-chapter-entry" key={item.id}>
        <div className="notebook-chapter-title"><button onClick={() => navigate(`/courses/${courseId}/notebooks/${notebookId}?chapter=${item.id}${mode === 'book' ? '&mode=book' : ''}`, { state: location.state })}>{index + 1}. {item.title}</button><span><button aria-label={`上移${item.title}`} disabled={index === 0 || ordering || noteDirty} onClick={() => void moveChapter(index, -1)}>↑</button><button aria-label={`下移${item.title}`} disabled={index === outline.chapters.length - 1 || ordering || noteDirty} onClick={() => void moveChapter(index, 1)}>↓</button></span></div>
        {item.sections.map((s) => <button className={`notebook-section-link ${selected?.id === s.id ? 'active' : ''}`} key={s.id} aria-current={selected?.id === s.id ? 'location' : undefined} onClick={() => open(s)}>{s.title}{s.user_locked ? ' · 已编辑' : ''}</button>)}
        {!item.sections.length && <small>{item.status === 'failed' ? '解析失败，请在资料页重试' : item.status === 'completed' ? '暂无可生成的小节，请检查来源' : '资料处理中'}</small>}
      </div>)}
      {outline.historical_sections.length > 0 && <details open={selected?.material_id === null}><summary>历史整理</summary><small>原有来源无法归入单讲，保留完整正文。</small>{outline.historical_sections.map((s) => <button className="notebook-section-link" key={s.id} onClick={() => open(s)}>{s.title}</button>)}</details>}
      {outline.removed_chapters.length > 0 && <details><summary>已移除资料的章节</summary>{outline.removed_chapters.map((c) => <div key={c.id}><strong>{c.title}</strong>{c.sections.map((s) => <button className="notebook-section-link" key={s.id} onClick={() => open(s)}>{s.title}</button>)}</div>)}</details>}
      <Link className="secondary-button link-button" to={uploadPath}>上传下一讲</Link>
    </nav><main ref={contentRef} className="notebook-content" aria-label="笔记本正文">
      {reading && <p role="status">正在按章节读取正文…</p>}
      {sectionParam && !selected ? <p role="alert">没有找到指定的小节；请从目录重新选择。</p> : chapterParam && !chapter && chapterParam !== 'history' ? <p role="alert">没有找到指定章节。</p> : <>
        {visibleChapters.map((item) => <section className="notebook-chapter-document" key={item.id}><h2>{item.title}{item.deleted_at ? ' · 资料已移除' : ''}</h2>{item.sections.map(renderSection)}{!item.sections.length && <p>本章暂时没有小节。<Link to={uploadPath}>检查资料与处理状态</Link></p>}</section>)}
        {visibleHistory.length > 0 && <section className="notebook-chapter-document"><h2>历史整理</h2>{visibleHistory.map(renderSection)}</section>}
        {!outline.chapters.length && !outline.historical_sections.length && <p>笔记本已准备好。<Link to={uploadPath}>上传第一讲资料</Link>，生成第一个章节。</p>}
        {selected && <div className="notebook-pagination"><button className="secondary-button" disabled={!previous} onClick={() => previous && open(previous)}>← 上一小节</button><button className="secondary-button" disabled={!next} onClick={() => next && open(next)}>下一小节 →</button></div>}
      </>}
    </main></div>
  </div>
}
