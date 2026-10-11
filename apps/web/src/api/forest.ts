import { request } from './http'
import type {
  CrossCourseRelation,
  CurriculumImport,
  CurriculumRow,
  ForestCourse,
  ForestJob,
  RelationType,
} from '../features/forest/types'

const base = '/api/v1/forest'
const json = (body: unknown) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
export const forestApi = {
  getForest: () => request<{ courses: ForestCourse[] }>(base),
  searchForest: (query: string) =>
    request<
      Array<{
        course_id: string
        course_name: string
        note_id: string
        title: string
        material_id: string | null
      }>
    >(`${base}/search?q=${encodeURIComponent(query)}`),
  updateForestCourse: (
    id: string,
    data: Partial<
      Pick<ForestCourse, 'semester' | 'level' | 'learning_state' | 'position' | 'prerequisites'>
    > & { expected_revision: number },
  ) => request<ForestCourse>(`${base}/courses/${id}`, { method: 'PATCH', ...json(data) }),
  getForestRelations: (status = 'all') =>
    request<CrossCourseRelation[]>(`${base}/relations?status=${status}`),
  createForestRelation: (data: {
    source_note_id: string
    target_note_id: string
    relation_type: RelationType
    reason: string
  }) => request<CrossCourseRelation>(`${base}/relations`, { method: 'POST', ...json(data) }),
  reviewForestRelation: (id: string, decision: 'confirm' | 'reject') =>
    request<CrossCourseRelation>(`${base}/relations/${id}/review`, {
      method: 'POST',
      ...json({ decision }),
    }),
  deleteForestRelation: (id: string) =>
    request<{ deleted: boolean }>(`${base}/relations/${id}`, { method: 'DELETE' }),
  listCurriculumImports: () => request<CurriculumImport[]>(`${base}/curriculum-imports`),
  createCurriculumImport: (data: FormData) =>
    request<CurriculumImport>(`${base}/curriculum-imports`, { method: 'POST', body: data }),
  getCurriculumImport: (id: string) =>
    request<CurriculumImport>(`${base}/curriculum-imports/${id}`),
  retryCurriculumImport: (id: string) =>
    request<CurriculumImport>(`${base}/curriculum-imports/${id}/retry`, { method: 'POST' }),
  confirmCurriculumImport: (id: string, rows: CurriculumRow[]) =>
    request<{ courses: ForestCourse[] }>(`${base}/curriculum-imports/${id}/confirm`, {
      method: 'POST',
      ...json({ rows }),
    }),
  suggestForestRelations: (id: string) =>
    request<ForestJob>(`${base}/courses/${id}/suggest-relations`, { method: 'POST' }),
  getForestJob: (id: string) => request<ForestJob>(`${base}/jobs/${id}`),
  getLatestForestJob: (id: string) => request<ForestJob | null>(`${base}/courses/${id}/latest-job`),
  retryForestJob: (id: string) =>
    request<ForestJob>(`${base}/jobs/${id}/retry`, { method: 'POST' }),
}
