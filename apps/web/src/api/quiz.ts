import { request } from './http'

/** 自测卷 DTO（v6 P10）：答案与解释不下发，判分在服务端 */
export type QuizItemDto = {
  id: string
  seq: number
  type: 'choice' | 'short'
  stem: string
  options: string[]
  /** 难度标签（v6 §7 第二批）：用户自定义原话（「挑战」「考研」），未指定为「自适应」 */
  difficulty?: string | null
  /** 用户状态随题下发（库为真源）：答题卡收藏/标记的初值 */
  favorite?: boolean
  marked?: boolean
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
  /** B1 结构化判分：简答题的要点命中明细（选择题为空数组） */
  points?: Array<{ point: string; hit: boolean }>
}

/** 错题本条目（§7 第一批）：最近一次仍答错的题，带历史错次与来源卷子 */
export type QuizMistake = {
  item_id: string
  quiz_id: string
  quiz_title: string
  material_id: string | null
  material_title: string | null
  seq: number
  type: 'choice' | 'short'
  stem: string
  options: string[]
  answer: string
  explanation: string
  last_answer: string
  last_at: string
  wrong_count: number
  difficulty?: string | null
  favorite?: boolean
  marked?: boolean
  dismissed?: boolean
}

/** 复习产物（§7）：复习提纲 / 易混概念对比，跨会话存储，支持收藏与删除 */
export type ReviewArtifactDto<T = unknown> = {
  id: string
  kind: 'review_outline' | 'concept_contrast'
  title: string
  payload: T
  favorite: boolean
  /** 移出复习（软移除）：面板不展示、会话卡片保留，可恢复 */
  dismissed?: boolean
  created_at: string
}

export type QuizItemFlags = { favorite?: boolean; marked?: boolean; dismissed?: boolean }

export const quizApi = {
  listQuizzes: (courseId: string, status: 'active' | 'completed' = 'active') =>
    request<QuizDto[]>(`/api/v1/courses/${courseId}/quizzes?status=${status}`),
  listMistakes: (courseId: string, limit = 200) =>
    request<QuizMistake[]>(`/api/v1/courses/${courseId}/quiz-mistakes?limit=${limit}`),
  setItemFlags: (itemId: string, flags: QuizItemFlags) =>
    request<{ item_id: string; favorite: boolean; marked: boolean; dismissed: boolean }>(
      `/api/v1/quiz-items/${itemId}/flags`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(flags) },
    ),
  listReviewArtifacts: (courseId: string, kind?: 'review_outline' | 'concept_contrast', includeDismissed = false) =>
    request<ReviewArtifactDto[]>(`/api/v1/courses/${courseId}/review-artifacts${kind ? `?kind=${kind}` : ''}${includeDismissed ? `${kind ? '&' : '?'}include_dismissed=1` : ''}`),
  listArtifactStates: (ids: string[]) =>
    request<ReviewArtifactDto[]>(`/api/v1/review-artifacts?ids=${ids.join(',')}`),
  updateArtifact: (artifactId: string, patch: { favorite?: boolean; dismissed?: boolean }) =>
    request<{ id: string; favorite: boolean; dismissed: boolean }>(
      `/api/v1/review-artifacts/${artifactId}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) },
    ),
  getQuiz: (quizId: string) =>
    request<QuizDto>(`/api/v1/quizzes/${quizId}`),
  submitAttempts: (quizId: string, answers: Array<{ item_id: string; answer: string }>) =>
    request<{ quiz_id: string; status: string; results: QuizAttemptResult[]; score: string }>(
      `/api/v1/quizzes/${quizId}/attempts`,
      {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      },
    ),
}
