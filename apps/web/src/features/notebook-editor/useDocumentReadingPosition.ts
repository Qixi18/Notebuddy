import { useEffect, useRef, useState, type RefObject } from 'react'
import { api, ApiError } from '../../api'
import type { NotebookReadingPosition } from '../../types'
import type { NotebookEditorHandle } from './NotebookEditor'

function scrollingElement(root: HTMLElement): HTMLElement {
  let parent = root.parentElement
  while (parent) {
    if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight) return parent
    parent = parent.parentElement
  }
  return (document.scrollingElement ?? document.documentElement) as HTMLElement
}

function editorRoot(editorRef: RefObject<NotebookEditorHandle | null>): HTMLElement | undefined {
  return editorRef.current?.editor?.view?.dom as HTMLElement | undefined
}

type PositionLoad = { key: string; position: NotebookReadingPosition | null; settled: boolean }

/** Restores/saves a course Notebook's position using stable Tiptap block IDs and a separate CAS revision. */
export function useDocumentReadingPosition({ courseId, notebookId, editorRef, ready, explicitLink, onRestore }: {
  courseId?: string
  notebookId?: string
  editorRef: RefObject<NotebookEditorHandle | null>
  ready: boolean
  explicitLink: boolean
  onRestore: (blockId: string) => void
}) {
  const key = courseId && notebookId ? `${courseId}:${notebookId}` : ''
  const [load, setLoad] = useState<PositionLoad>({ key: '', position: null, settled: false })
  const canWrite = useRef(false)
  const revision = useRef(0)
  const restoreRef = useRef(onRestore)
  restoreRef.current = onRestore
  const bookmark = load.key === key && load.settled ? load.position : undefined
  const bookmarkReady = Boolean(key && load.key === key && load.settled)

  useEffect(() => {
    if (!courseId || courseId === 'unbound' || !notebookId) return
    let active = true
    canWrite.current = false
    revision.current = 0
    setLoad({ key, position: null, settled: false })
    void api.getReadingPosition(courseId, notebookId).then(position => {
      if (!active) return
      revision.current = position?.revision ?? 0
      canWrite.current = true
      setLoad({ key, position, settled: true })
    }).catch(() => {
      if (active) setLoad({ key, position: null, settled: true })
    })
    return () => { active = false }
  }, [courseId, key, notebookId])

  const restoredKey = useRef('')
  useEffect(() => {
    if (!ready || !bookmarkReady || !key) return
    const root = editorRoot(editorRef)
    if (!root || restoredKey.current === key) return
    restoredKey.current = key
    if (explicitLink) return
    const blockId = bookmark?.block_id
    if (!blockId) return
    const target = Array.from(root.children).find(node => node.getAttribute('data-block-id') === blockId) as HTMLElement | undefined
    if (!target) return
    editorRef.current?.focusBlock(blockId)
    restoreRef.current(blockId)
    const frame = requestAnimationFrame(() => {
      const host = scrollingElement(root)
      const top = host === document.scrollingElement || host === document.documentElement ? 0 : host.getBoundingClientRect().top
      const rect = target.getBoundingClientRect()
      host.scrollTop += rect.top - top - 80 + Math.max(0, rect.height) * bookmark.section_offset
    })
    return () => cancelAnimationFrame(frame)
  }, [bookmark, bookmarkReady, editorRef, explicitLink, key, ready])

  useEffect(() => {
    if (!ready || !bookmarkReady || !key || !courseId || courseId === 'unbound' || !notebookId) return
    const root = editorRoot(editorRef)
    if (!root) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let pending: { block_id: string; section_offset: number } | undefined
    let inFlight = false
    let last = bookmark ? `${bookmark.block_id ?? ''}:${bookmark.section_offset.toFixed(3)}` : ''

    const drain = async () => {
      if (inFlight || !pending || !canWrite.current) return
      const position = pending
      pending = undefined
      const value = `${position.block_id}:${position.section_offset.toFixed(3)}`
      if (value === last) return
      inFlight = true
      try {
        const saved = await api.putReadingPosition(courseId, notebookId, {
          chapter_id: null, note_id: null, block_id: position.block_id,
          mode: 'book', section_offset: position.section_offset, expected_revision: revision.current,
        })
        revision.current = saved.revision
        last = value
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) canWrite.current = false
      } finally {
        inFlight = false
        if (pending) void drain()
      }
    }

    const capture = () => {
      const host = scrollingElement(root)
      const top = host === document.scrollingElement || host === document.documentElement ? 0 : host.getBoundingClientRect().top
      const block = Array.from(root.children).find(node => node.hasAttribute('data-block-id') && node.getBoundingClientRect().bottom > top + 80)
      const blockId = block?.getAttribute('data-block-id')
      if (!block || !blockId) return
      const rect = block.getBoundingClientRect()
      pending = { block_id: blockId, section_offset: Math.max(0, Math.min(1, (top + 80 - rect.top) / Math.max(1, rect.height))) }
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => { void drain() }, 650)
    }

    document.addEventListener('scroll', capture, { capture: true, passive: true })
    return () => {
      document.removeEventListener('scroll', capture, true)
      if (timer) clearTimeout(timer)
      void drain()
    }
  }, [bookmark, bookmarkReady, courseId, editorRef, key, notebookId, ready])
}
