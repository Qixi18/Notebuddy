import type { Note, NoteRevision, NoteSourceRef, WebSource } from '../types'
import { request } from './http'

export const noteApi = {
  listNotes: (courseId: string) => request<Note[]>(`/api/v1/courses/${courseId}/notes`),
  getNote: (noteId: string) => request<Note>(`/api/v1/notes/${noteId}`),
  getNoteRevisions: (noteId: string) => request<NoteRevision[]>(`/api/v1/notes/${noteId}/revisions`),
  getNoteWebSources: (noteId: string) => request<WebSource[]>(`/api/v1/notes/${noteId}/web-sources`),
  getNoteSources: (noteId: string) => request<NoteSourceRef[]>(`/api/v1/notes/${noteId}/sources`),
  updateNote: (noteId: string, contentMarkdown: string, expectedRevisionNumber: number) => request<Note>(`/api/v1/notes/${noteId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content_markdown: contentMarkdown, expected_revision_number: expectedRevisionNumber }),
  }),
  listSuggestions: (noteId: string) => request<Array<{ id: string; note_id: string; proposed_markdown: string; impact: string; status: string }>>(`/api/v1/notes/${noteId}/suggestions`),
  reviewSuggestion: (noteId: string, suggestionId: string, decision: 'confirm' | 'reject', note?: string, finalMarkdown?: string) => request<Note>(`/api/v1/notes/${noteId}/suggestions/${suggestionId}/review`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    // final_markdown：逐块审查后前端拼装的最终正文（部分采纳）；undefined 时后端沿用建议原文
    body: JSON.stringify({ decision, note, final_markdown: finalMarkdown }),
  }),
}
