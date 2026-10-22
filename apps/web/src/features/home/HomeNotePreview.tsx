import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import type { HomeLeafPreview } from './HomeCourseTree'
import './note-preview.css'

function excerpt(markdown: string) {
  const paragraph = markdown.split('\n').map(line => line.trim()).find(line => line && !/^(#|\$\$|---)/.test(line)) ?? ''
  const plain = paragraph.replace(/^[-*]\s+/, '').replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`]/g, '')
  return plain.length > 145 ? `${plain.slice(0, 145)}…` : plain
}
export function HomeNotePreview({ id, preview, courseId, onEnter, onLeave, onDismiss }: {
  id: string; preview: HomeLeafPreview; courseId: string
  onEnter: () => void; onLeave: () => void; onDismiss: () => void
}) {
  const [loaded, setLoaded] = useState<{ id: string; text: string }>()
  const host = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false })
  const noteId = preview.leaf.section.id
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
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); observer?.disconnect() }
  }, [preview.target, text])
  useEffect(() => {
    let active = true
    void api.getNote(noteId).then(note => {
      if (active) setLoaded({ id: noteId, text: note.course_id === courseId && note.notebook_id === preview.book.id ? excerpt(note.content_markdown) : '预览暂不可用，点击叶子打开笔记。' })
    }).catch(() => { if (active) setLoaded({ id: noteId, text: '预览暂不可用，点击叶子打开笔记。' }) })
    return () => { active = false }
  }, [noteId, preview.book.id, courseId])
  useEffect(() => {
    const dismiss = (event: KeyboardEvent) => { if (event.key === 'Escape') onDismiss() }
    window.addEventListener('keydown', dismiss)
    return () => window.removeEventListener('keydown', dismiss)
  }, [onDismiss])
  return createPortal(<div ref={host} className="home-leaf-preview" id={id} role="tooltip" style={{ left: position.left, top: position.top, visibility: position.ready ? 'visible' : 'hidden' }} onMouseEnter={onEnter} onMouseLeave={onLeave}>
    <small>{preview.book.title} <span>·</span> {preview.leaf.chapterTitle}</small>
    <strong>{preview.leaf.section.title}</strong>
    <p>{text ?? '正在读取笔记…'}</p>
    <span className="home-leaf-preview-hint">点击叶子，打开完整笔记 ↗</span>
  </div>, document.body)
}
