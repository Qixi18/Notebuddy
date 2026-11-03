import { api } from '../../../api'
import type { NotebookDocumentResponse, NotebookRead, NotebookRevision, NotebookRevisionSummary } from '../../../types'

/**
 * Notebook 身份：课程归属是可选的，未分类 Notebook 没有课程 ID。
 *
 * 这里用判别联合而不是 `courseId = 'unbound'` 占位值：占位值一旦进入通用 API，
 * 就会被当成真实课程 ID 传播（路由、草稿键、请求参数都会变脏）。
 */
export type NotebookIdentity =
  | { kind: 'course'; courseId: string; notebookId: string }
  | { kind: 'unbound'; notebookId: string }

/** 未分类 Notebook 在展示层的占位结构；调用方必须自己检查 `identity.kind`。 */
function unboundNotebook(book: { id: string; title: string; created_at?: string; updated_at?: string; cover_url?: string | null }): NotebookRead {
  return {
    id: book.id,
    course_id: '',
    title: book.title,
    tree_slot: 0,
    display_order: 0,
    order_revision: 0,
    is_default: false,
    chapters: [],
    historical_sections: [],
    removed_chapters: [],
  } as NotebookRead
}

/** Normalizes identity-specific routes into one Notebook workspace contract. */
export function notebookApiAdapter(identity: NotebookIdentity) {
  const { notebookId } = identity
  const unbound = identity.kind === 'unbound'
  /* null 表示"没有课程归属"，不再用伪课程 ID；调用方需要 URL 时必须显式判空。 */
  const courseId: string | null = identity.kind === 'course' ? identity.courseId : null
  const courseRoute = () => {
    if (identity.kind !== 'course') throw new Error('未分类 Notebook 没有课程路由')
    return identity.courseId
  }
  return {
    courseId,
    identity,
    getNotebook: async (): Promise<NotebookRead> => {
      if (!unbound) return api.getNotebookById(courseRoute(), notebookId)
      return unboundNotebook(await api.getUnboundNotebook(notebookId))
    },
    getDocument: (): Promise<NotebookDocumentResponse> => unbound
      ? api.getUnboundNotebookDocument(notebookId)
      : api.getNotebookDocument(courseRoute(), notebookId),
    rename: async (title: string): Promise<NotebookRead> => {
      if (!unbound) return api.renameNotebook(courseRoute(), notebookId, title)
      return unboundNotebook(await api.renameUnboundNotebook(notebookId, title))
    },
    uploadAttachment: (file: File) => unbound
      ? api.uploadUnboundNotebookAttachment(notebookId, file)
      : api.uploadNotebookAttachment(courseRoute(), notebookId, file),
    listRevisions: (): Promise<NotebookRevisionSummary[]> => unbound
      ? api.listUnboundNotebookRevisions(notebookId)
      : api.listNotebookRevisions(courseRoute(), notebookId),
    getRevision: (revision: number): Promise<NotebookRevision> => unbound
      ? api.getUnboundNotebookRevision(notebookId, revision)
      : api.getNotebookRevision(courseRoute(), notebookId, revision),
    restoreRevision: (revision: number, expectedRevision: number): Promise<NotebookDocumentResponse> => unbound
      ? api.restoreUnboundNotebookRevision(notebookId, revision, expectedRevision)
      : api.restoreNotebookRevision(courseRoute(), notebookId, revision, expectedRevision),
  }
}
