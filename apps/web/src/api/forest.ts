import { request } from './http'
import type { CourseTree } from '../types'
import type {
  CurriculumImport,
  CurriculumRow,
  ForestCourse,
  ForestJob,
  ForestSearchResult,
  NotebookRelation,
  RelationType,
} from '../features/forest/types'

const base = '/api/v1/forest'
const json = (body: unknown) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
export const forestApi = {
  getCourseTree: (courseId: string) => request<CourseTree>(`${base}/courses/${courseId}/tree`),
  getForest: () => request<{ courses: ForestCourse[] }>(base),
  searchForest: (query: string) =>
    request<ForestSearchResult[]>(`${base}/search?q=${encodeURIComponent(query)}`),
  updateForestCourse: (
    id: string,
    data: Partial<
      Pick<ForestCourse, 'semester' | 'level' | 'learning_state' | 'position' | 'prerequisites'>
    > & { expected_revision: number },
  ) => request<ForestCourse>(`${base}/courses/${id}`, { method: 'PATCH', ...json(data) }),
  getForestRelations: () => request<NotebookRelation[]>(`${base}/relations`),
  createForestRelation: (data: {
    source_notebook_id: string
    target_notebook_id: string
    relation_type: RelationType
    reason: string
    source_block_id?: string | null
    target_block_id?: string | null
  }) => request<NotebookRelation>(`${base}/relations`, { method: 'POST', ...json(data) }),
  deleteForestRelation: (id: string) =>
    request<{ deleted: boolean }>(`${base}/relations/${id}`, { method: 'DELETE' }),
  refreshForestRelation: (id: string) =>
    request<NotebookRelation>(`${base}/relations/${id}/refresh`, { method: 'POST' }),
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
