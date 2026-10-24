import { request } from './http'

/** 自测卷 DTO（v6 P10）：答案与解释不下发，判分在服务端 */
export type QuizItemDto = {
  id: string
  seq: number
  type: 'choice' | 'short'
  stem: string
  options: string[]
}

export type QuizDto = {
  id: string
  title: string
  status: string
  items: QuizItemDto[]
}

export type QuizAttemptResult = {
  item_id: string
  seq: number
  correct: boolean
  answer: string
  explanation: string
  comment: string
}

export const quizApi = {
  listQuizzes: (courseId: string, status: 'active' | 'completed' = 'active') =>
    request<QuizDto[]>(`/api/v1/courses/${courseId}/quizzes?status=${status}`),
  submitAttempts: (quizId: string, answers: Array<{ item_id: string; answer: string }>) =>
    request<{ quiz_id: string; status: string; results: QuizAttemptResult[]; score: string }>(
      `/api/v1/quizzes/${quizId}/attempts`,
      {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      },
    ),
}
