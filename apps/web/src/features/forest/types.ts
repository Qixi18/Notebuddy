export type ForestLevel = 'foundation' | 'professional' | 'application' | 'unspecified'
export type LearningState = 'planned' | 'learning' | 'completed'
export type ForestCourse = {
  course_id: string
  name: string
  semester: number | null
  level: ForestLevel
  learning_state: LearningState
  position: number
  revision: number
  note_count: number
  material_count: number
  prerequisites: string[]
}
export type RelationType = 'related' | 'prerequisite' | 'application'
export type CrossCourseRelation = {
  id: string
  source_course_id: string
  target_course_id: string
  source_note_id: string
  target_note_id: string
  source_title: string
  target_title: string
  source_course_name: string
  target_course_name: string
  relation_type: RelationType
  reason: string
  status: 'pending' | 'confirmed' | 'rejected'
  origin: 'manual' | 'ai'
  source_revision: number
  target_revision: number
  stale: boolean
  source_ref_ids: string[]
  target_ref_ids: string[]
}
export type CurriculumRow = {
  key: string
  name: string
  semester: number | null
  level: ForestLevel
  prerequisites: string[]
  source_label: string
  source_excerpt: string
  existing_course_id: string | null
}
export type CurriculumImport = {
  id: string
  status: 'pending' | 'processing' | 'preview' | 'confirmed' | 'failed'
  filename: string | null
  mode: string | null
  warnings: string[]
  rows: CurriculumRow[]
  error_message: string | null
  job_id: string | null
}
export type ForestJob = {
  id: string
  kind: 'curriculum_import' | 'cross_course_relations'
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  error_message: string | null
}
export type Camera = { x: number; y: number; k: number }
export const levelLabels: Record<ForestLevel, string> = {
  foundation: '基础课程',
  professional: '专业课程',
  application: '综合应用',
  unspecified: '未分类',
}
export const stateLabels: Record<LearningState, string> = {
  planned: '未开始',
  learning: '在学',
  completed: '已完成',
}
export const relationLabels: Record<RelationType, string> = {
  related: '知识关联',
  prerequisite: '先修基础',
  application: '应用关系',
}
