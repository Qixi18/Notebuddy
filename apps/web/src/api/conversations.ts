import type { Conversation, ConversationMessage } from '../types'
import { request } from './http'

export type ConversationOwnership = {
  /** 归属：course=整门课程 / global=跨课程 / note=锁定笔记 */
  scope?: 'course' | 'global' | 'note'
  noteId?: string | null
  noteTitle?: string | null
}

export const conversationApi = {
  listConversations: (courseId: string) => request<Conversation[]>(`/api/v1/courses/${courseId}/conversations`),
  renameConversation: (conversationId: string, title: string) =>
    request<Conversation>(`/api/v1/conversations/${conversationId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (conversationId: string) =>
    request<void>(`/api/v1/conversations/${conversationId}`, { method: 'DELETE' }),
  createConversation: (courseId: string, title = '新对话', ownership?: ConversationOwnership) => {
    const scope = ownership?.scope ?? 'course'
    return request<Conversation>(`/api/v1/courses/${courseId}/conversations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        default_scope: scope,
        scope,
        /* 只有锁定笔记的会话才带快照，其余由后端忽略 */
        note_id: scope === 'note' ? ownership?.noteId ?? null : null,
        note_title: scope === 'note' ? ownership?.noteTitle ?? null : null,
      }),
    })
  },
  listConversationMessages: (conversationId: string) => request<ConversationMessage[]>(`/api/v1/conversations/${conversationId}/messages`),
  sendConversationMessage: (conversationId: string, payload: { question: string; teacher_persona?: string; material_id?: string; page_number?: number; learning_goal?: string; allow_web?: boolean; idempotency_key?: string; scope?: 'course' | 'global' | 'note'; note_id?: string | null; note_title?: string | null }) =>
    request<ConversationMessage>(`/api/v1/conversations/${conversationId}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ teacher_persona: 'elf', ...payload }),
    }),
}
