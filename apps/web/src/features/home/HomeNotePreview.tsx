import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { api } from '../../api'
import type { HomeLeafPreview } from './HomeCourseTree'
import './note-preview.css'

function PreviewMarkdown({ text, inline = false }: { text: string; inline?: boolean }) {
  return <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[[rehypeKatex, { strict: false, trust: false }]]}
    skipHtml disallowedElements={['a', 'img']} unwrapDisallowed components={inline ? { p: 'span' } : undefined}>{text}</ReactMarkdown>
}
export function HomeNotePreview({ id, preview, courseId, onEnter, onLeave, onDismiss }: {
  id: string; preview: HomeLeafPreview; courseId: string
  onEnter: () => void; onLeave: () => void; onDismiss: () => void
}) {
  const [loaded, setLoaded] = useState<{ id: string; text: string }>()
  const host = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false })
  const blockId = preview.leaf.section.block_id ?? preview.leaf.section.id
  const noteId = JSON.stringify([preview.book.id, blockId, preview.leaf.section.revision_number])
  const text = loaded?.id === noteId ? loaded.text : undefined
  useLayoutEffect(() => {
    const measure = () => {
      const bounds = host.current?.getBoundingClientRect(), anchor = preview.target.getBoundingClientRect()
      if (!bounds) return
      const gap = 12, above = anchor.top - bounds.height - gap
      const preferred = above >= gap ? above : anchor.bottom + gap
      setPosition({ left: Math.max(gap + bounds.width / 2, Math.min(innerWidth - gap - bounds.width / 2, anchor.left + anchor.width / 2)), top: Math.max(gap, Math.min(innerHeight - gap - bounds.height, preferred)), ready: true })
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure)
    if (preview.target.ownerSVGElement) observer?.observe(preview.target.ownerSVGElement)
    if (host.current) observer?.observe(host.current)
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); observer?.disconnect() }
  }, [preview.target, text])
  useEffect(() => {
    let active = true
    if (preview.book.course_id !== courseId || preview.leaf.section.notebook_id !== preview.book.id) return
    void api.getNotebookSections(courseId, preview.book.id).then(sections => {
      const section = sections.find(row => row.block_id === blockId)
      if (active) setLoaded({ id: noteId, text: section ? section.excerpt.trim()
        || '此小节暂时没有正文，点击叶子打开笔记。' : '预览暂不可用，点击叶子打开笔记。' })
    }).catch(() => { if (active) setLoaded({ id: noteId, text: '预览暂不可用，点击叶子打开笔记。' }) })
    return () => { active = false }
  }, [noteId, blockId, preview.book.id, preview.book.course_id, preview.leaf.section.notebook_id, courseId])
  useEffect(() => {
    const dismiss = (event: KeyboardEvent) => { if (event.key === 'Escape') onDismiss() }
    window.addEventListener('keydown', dismiss)
    return () => window.removeEventListener('keydown', dismiss)
  }, [onDismiss])
  return createPortal(<div ref={host} className="home-leaf-preview" id={id} role="tooltip" style={{ left: position.left, top: position.top, visibility: position.ready ? 'visible' : 'hidden' }} onMouseEnter={onEnter} onMouseLeave={onLeave}>
    <small>{preview.book.title} <span>·</span> {preview.leaf.chapterTitle}</small>
    <strong><PreviewMarkdown text={preview.leaf.section.title} inline /></strong>
    <div className="home-leaf-preview-content"><PreviewMarkdown text={text ?? '正在读取笔记…'} /></div>
    <span className="home-leaf-preview-hint">点击叶子，打开完整笔记 ↗</span>
  </div>, document.body)
}
