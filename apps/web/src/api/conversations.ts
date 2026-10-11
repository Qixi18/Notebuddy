import type { Conversation, ConversationMessage } from '../types'
import { request } from './http'

export const conversationApi = {
  listConversations: (courseId: string) => request<Conversation[]>(`/api/v1/courses/${courseId}/conversations`),
  createConversation: (courseId: string, title = '新对话') => request<Conversation>(`/api/v1/courses/${courseId}/conversations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, default_scope: 'course' }),
  }),
  listConversationMessages: (conversationId: string) => request<ConversationMessage[]>(`/api/v1/conversations/${conversationId}/messages`),
  sendConversationMessage: (conversationId: string, payload: { question: string; teacher_persona?: string; material_id?: string; page_number?: number; learning_goal?: string; allow_web?: boolean; idempotency_key?: string }) =>
    request<ConversationMessage>(`/api/v1/conversations/${conversationId}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ teacher_persona: 'elf', ...payload }),
    }),
}
