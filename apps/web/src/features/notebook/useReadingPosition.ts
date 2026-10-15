import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { NotebookReadingPosition, NotebookSection } from '../../types'
import { pendingPosition, positionWriter, type Position } from './readingPosition'

export function useReadingPosition(courseId: string, bookId: string, bookmark: NotebookReadingPosition | null | undefined, selected: NotebookSection | undefined, mode: 'book' | 'chapter', ready: boolean, targetKey: string, initialOffset: number, container: RefObject<HTMLElement | null>) {
  const [error, setError] = useState<string>()
  const restored = useRef<string | undefined>(undefined)
  const positions = useRef(new Map<string, Position>())
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const key = `${courseId}:${bookId}`
  const writer = useMemo(() => bookmark === undefined || !bookId ? undefined : positionWriter(courseId, bookId, bookmark), [courseId, bookId, bookmark])
  useEffect(() => { setError(pendingPosition(courseId, bookId) ? '上次阅读位置保存失败；进度仍暂存，请重试保存当前位置。' : undefined) }, [courseId, bookId])
  const save = useCallback(() => {
    const position = positions.current.get(key)
    if (!position || !writer) return
    void writer.save(position).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '阅读位置保存失败'))
  }, [key, writer])
  useEffect(() => {
    if (!ready || !selected || !container.current || restored.current === targetKey) return
    const element = document.getElementById(`section-${selected.id}`)
    if (!element) return
    const host = container.current
    host.scrollTop += element.getBoundingClientRect().top - host.getBoundingClientRect().top + element.getBoundingClientRect().height * initialOffset
    restored.current = targetKey
    positions.current.set(key, { chapter_id: selected.material_id, note_id: selected.id, mode, section_offset: initialOffset })
  }, [ready, selected?.id, mode, targetKey, initialOffset, container, key])
  useLayoutEffect(() => {
    const host = container.current
    if (!host || !ready || !selected || bookmark === undefined) return
    function samplePosition() {
      const top = host!.getBoundingClientRect().top
      const elements = [...host!.querySelectorAll<HTMLElement>('.notebook-section')]
      const element = elements.filter(item => item.getBoundingClientRect().top <= top + 2).at(-1) ?? elements[0]
      if (!element) return
      const rect = element.getBoundingClientRect()
      if (rect.height <= 0) return
      positions.current.set(key, { chapter_id: element.dataset.chapter || null, note_id: element.dataset.note!, mode, section_offset: Math.min(1, Math.max(0, (top - rect.top) / rect.height)) })
    }
    function scroll() {
      samplePosition()
      clearTimeout(timer.current)
      timer.current = setTimeout(save, 600)
    }
    // Layout cleanup samples before React removes the reading DOM. The final
    // native scroll event may still be queued when navigation/pagehide happens.
    const leave = () => { clearTimeout(timer.current); samplePosition(); save() }
    host.addEventListener('scroll', scroll, { passive: true })
    window.addEventListener('pagehide', leave)
    return () => { host.removeEventListener('scroll', scroll); window.removeEventListener('pagehide', leave); leave() }
  }, [key, ready, selected?.id, mode, bookmark, container, save])
  async function retry() {
    try { await writer?.resume(); setError(undefined); save() }
    catch (cause) { setError(cause instanceof Error ? cause.message : '阅读位置重试失败') }
  }
  return { error, retry }
}
