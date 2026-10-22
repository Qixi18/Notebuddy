import type { ReactNode } from 'react'
import type { CourseTree, SectionRead } from '../../types'
import type { Camera, CrossCourseRelation, ForestCourse } from '../forest/types'
import type { SavedSlot } from './layout'

export type KnowledgeTreeView = {
  layoutVersion?: string
  camera: Camera
  viewport: { width: number; height: number }
  slots: Record<string, SavedSlot>
  focusedCourseId?: string
  contents?: { courseId: string; notebookId?: string }
  revealedNoteId?: string
  knownNotebookIds?: Record<string, string[]>
}
export type KnowledgeTreeSceneProps = {
  courses: ForestCourse[]
  trees: CourseTree[]
  mode?: 'home' | 'forest'
  initialView?: KnowledgeTreeView
  onViewChange?: (view: KnowledgeTreeView) => void
  focusCourseId?: string
  onFocusCourse?: (courseId: string) => void
  search?: string
  pinnedNoteIds?: string[]
  relations?: CrossCourseRelation[]
  selectedRelationId?: string
  onVisibleCourseIdsChange?: (courseIds: string[]) => void
  onRoot: (courseId: string) => void
  onNotebook: (courseId: string, notebookId: string) => void
  onNote: (courseId: string, notebookId: string, section: SectionRead) => void
  onRelation: (relation: CrossCourseRelation) => void
  className?: string
  toolbar?: ReactNode
  backdrop?: ReactNode
  onToggleHome?: (courseId: string) => void
  homeBusyCourseId?: string
}
