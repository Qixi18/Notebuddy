import { useEffect, useMemo, useRef } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import { courseCanopyGeometry } from '../tree/courseCanopyGeometry'
import { CourseCanopy, type LeafPreview } from '../tree/CourseCanopy'
import type { GrowthAnimations } from '../tree/growth/useGrowthPlayback'
import { playTreeGrowth } from '../tree/growth/paint'
import { growthVisible } from '../tree/growth/visibility'
import '../tree/knowledge-tree.css'

export { homePreviewBooks } from '../tree/courseCanopyGeometry'
export type HomeLeafPreview = LeafPreview

export function HomeCourseTree({ courseId, books, selectedBookId, previewId, previewNoteId, growth, onPreview, onLeave, onNotebook, onNote }: {
  courseId: string; books: NotebookRead[]; selectedBookId?: string; previewId: string; previewNoteId?: string
  growth?: GrowthAnimations
  onPreview: (preview: HomeLeafPreview) => void; onLeave: () => void
  onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
}) {
  const root = useRef<SVGGElement>(null)
  const { bounds, items, variant } = useMemo(() => courseCanopyGeometry(courseId, books, selectedBookId), [books, courseId, selectedBookId])
  useEffect(() => {
    const element = root.current
    if (!element || !growth || !growthVisible(element)) return
    const course = growth.courses.has(courseId)
    const bookIds = new Set(books.map(book => book.id))
    const growingBooks = new Set([...growth.books].filter(id => bookIds.has(id)))
    const growingNotes = growth.sections
    if (!course && !growingBooks.size && !growingNotes.size) return
    const playback = playTreeGrowth(element, { course, books: growingBooks, notes: growingNotes })
    const finish = () => playback.finish()
    element.addEventListener('pointerdown', finish, true)
    element.addEventListener('focusin', finish, true)
    return () => {
      element.removeEventListener('pointerdown', finish, true)
      element.removeEventListener('focusin', finish, true)
      finish()
    }
  }, [growth, courseId, books])
  return <svg className="home-course-tree" viewBox={`${bounds.x - 18} ${bounds.y - 8} ${bounds.width + 36} ${bounds.height + 16}`} preserveAspectRatio="xMidYMax meet" aria-label="课程知识树，枝干打开笔记本，叶子打开知识点">
    <g ref={root}><CourseCanopy canopy={{ items, variant, bounds }} empty={!books.length} previewId={previewId} previewNoteId={previewNoteId} onPreview={onPreview} onLeave={onLeave} onNotebook={onNotebook} onNote={onNote} growingBooks={growth?.books} growingNotes={growth?.sections} /></g>
  </svg>
}
