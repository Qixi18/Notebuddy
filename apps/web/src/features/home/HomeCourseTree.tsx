import { useMemo } from 'react'
import type { NotebookRead, SectionRead } from '../../types'
import { courseCanopyGeometry } from '../tree/courseCanopyGeometry'
import { CourseCanopy, type LeafPreview } from '../tree/CourseCanopy'
import '../tree/knowledge-tree.css'

export { homePreviewBooks } from '../tree/courseCanopyGeometry'
export type HomeLeafPreview = LeafPreview

export function HomeCourseTree({ courseId, books, selectedBookId, previewId, previewNoteId, onPreview, onLeave, onNotebook, onNote }: {
  courseId: string; books: NotebookRead[]; selectedBookId?: string; previewId: string; previewNoteId?: string
  onPreview: (preview: HomeLeafPreview) => void; onLeave: () => void
  onNotebook: (book: NotebookRead) => void; onNote: (book: NotebookRead, section: SectionRead) => void
}) {
  const { bounds, items, variant } = useMemo(() => courseCanopyGeometry(courseId, books, selectedBookId), [books, courseId, selectedBookId])
  return <svg className="home-course-tree" viewBox={`${bounds.x - 18} ${bounds.y - 8} ${bounds.width + 36} ${bounds.height + 16}`} preserveAspectRatio="xMidYMax meet" aria-label="课程知识树，枝干打开笔记本，叶子打开知识点">
    <CourseCanopy canopy={{ items, variant, bounds }} empty={!books.length} previewId={previewId} previewNoteId={previewNoteId} onPreview={onPreview} onLeave={onLeave} onNotebook={onNotebook} onNote={onNote} />
  </svg>
}
