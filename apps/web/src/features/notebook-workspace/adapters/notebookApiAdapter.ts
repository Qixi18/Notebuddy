import { api } from '../../../api'
import type { NotebookDocumentResponse, NotebookRead, NotebookRevision, NotebookRevisionSummary } from '../../../types'

export type NotebookIdentity =
  | { kind: 'course'; courseId: string; notebookId: string }
  | { kind: 'unbound'; notebookId: string }

/** Normalizes identity-specific routes into one Notebook workspace contract. */
export function notebookApiAdapter(identity: NotebookIdentity) {
  const { notebookId } = identity
  const unbound = identity.kind === 'unbound'
  const courseId = unbound ? 'unbound' : identity.courseId
  return {
    courseId,
    getNotebook: async (): Promise<NotebookRead> => {
      if (!unbound) return api.getNotebookById(identity.courseId, notebookId)
      const book = await api.getUnboundNotebook(notebookId)
      return {
        ...book, course_id: '', tree_slot: 0, display_order: 0, order_revision: 0,
        is_default: false, chapters: [], historical_sections: [], removed_chapters: [],
      } as NotebookRead
    },
    getDocument: (): Promise<NotebookDocumentResponse> => unbound
      ? api.getUnboundNotebookDocument(notebookId)
      : api.getNotebookDocument(identity.courseId, notebookId),
    rename: async (title: string): Promise<NotebookRead> => {
      if (!unbound) return api.renameNotebook(identity.courseId, notebookId, title)
      const book = await api.renameUnboundNotebook(notebookId, title)
      return {
        ...book, course_id: '', tree_slot: 0, display_order: 0, order_revision: 0,
        is_default: false, chapters: [], historical_sections: [], removed_chapters: [],
      } as NotebookRead
    },
    uploadAttachment: (file: File) => unbound
      ? api.uploadUnboundNotebookAttachment(notebookId, file)
      : api.uploadNotebookAttachment(identity.courseId, notebookId, file),
    listRevisions: (): Promise<NotebookRevisionSummary[]> => unbound
      ? api.listUnboundNotebookRevisions(notebookId)
      : api.listNotebookRevisions(identity.courseId, notebookId),
    getRevision: (revision: number): Promise<NotebookRevision> => unbound
      ? api.getUnboundNotebookRevision(notebookId, revision)
      : api.getNotebookRevision(identity.courseId, notebookId, revision),
    restoreRevision: (revision: number, expectedRevision: number): Promise<NotebookDocumentResponse> => unbound
      ? api.restoreUnboundNotebookRevision(notebookId, revision, expectedRevision)
      : api.restoreNotebookRevision(identity.courseId, notebookId, revision, expectedRevision),
  }
}
