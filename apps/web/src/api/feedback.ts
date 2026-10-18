import type { Feedback } from '../types'
import { request } from './http'

export const feedbackApi = {
  saveFeedback: (courseId: string, payload: { target_type: string; target_id: string; category: string; comment?: string }) => request<Feedback>(`/api/v1/courses/${courseId}/feedback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
}
