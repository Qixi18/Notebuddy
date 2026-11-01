/**
 * 旧 Note 兼容 API（**退役中，新业务不得使用**）。
 *
 * 2026-11-01 复审结论：新业务一律走 Notebook API（`./notebook`）；本文件的
 * `Note`/`NoteSuggestion` 端点属于历史兼容边界，只在旧数据迁移、审计与历史
 * 引用排查时保留。它已从 `src/api.ts` 的 `api` 聚集中移除，避免新代码继续误用。
 *
 * 删除条件（全部满足才可删）：全仓无运行时 import、无测试依赖、后端旧端点经
 * 数据审计确认不再需要兼容。
 */
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
  // P4 课程级待确认建议：改动栏语义是「本课程的待确认改动」（不承诺只属于本会话）
  listCourseSuggestions: (courseId: string) => request<Array<{ id: string; note_id: string; proposed_markdown: string; impact: string; status: string; note_title?: string }>>(`/api/v1/courses/${courseId}/note-suggestions?status=pending`),
  reviewSuggestion: (noteId: string, suggestionId: string, decision: 'confirm' | 'reject', note?: string, finalMarkdown?: string) => request<Note>(`/api/v1/notes/${noteId}/suggestions/${suggestionId}/review`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    // final_markdown：逐块审查后前端拼装的最终正文（部分采纳）；undefined 时后端沿用建议原文
    body: JSON.stringify({ decision, note, final_markdown: finalMarkdown }),
  }),
}
