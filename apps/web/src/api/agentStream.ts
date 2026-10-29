import type { AssistantSource } from '../types'

/**
 * agent SSE 帧解析（纯函数、零运行时依赖）。
 *
 * 单独成文件是为了让 ``node --test`` 能直接以 strip-types 方式导入测试；
 * ``agent.ts`` 的流式客户端与这里共享同一套事件类型与解析规则。
 */

export type AgentScope = 'note' | 'course' | 'global'

export type AgentStepEvent = {
  type: 'step'
  tool: string
  detail: string
  status: 'running' | 'done'
  duration_ms?: number | null
  /** Tool artifacts already created, preserved if the stream ends before `final`. */
  suggestions?: AgentSuggestion[]
}

export type AgentDeltaEvent = { type: 'delta'; text: string }

/** 思考边界信号：后端只告知「进入/离开思考」，从不携带思维链原文。 */
export type AgentThinkingEvent = { type: 'thinking' }

export type AgentNoticeEvent = { type: 'notice'; text: string }

export type AgentSuggestion =
  | { type: 'notebook_edit_suggestion'; id: string; notebook_id: string; notebook_title: string; base_revision: number; impact: string }
  | { type: 'knowledge_proposal'; id: string; name: string }
  | { type: 'quiz'; id: string; quiz_id: string; title: string; item_count: number }
  | { type: 'review_outline'; id: string; artifact_id?: string; favorite?: boolean; title: string; module_count: number; item_count: number; modules: { title: string; priority: 'high' | 'medium' | 'low'; items: { point: string; ref?: string }[] }[] }
  | { type: 'concept_contrast'; id: string; artifact_id?: string; pair_count: number; pairs: { a: string; b: string; core: string; dimensions: { name: string; a: string; b: string }[]; anchor?: string }[] }

export type AgentProcessTrace = {
  /** 思考耗时（毫秒）。后端只存时长，思维链原文既不外发也不落库。 */
  thinking_ms?: number
  steps: { tool: string; detail: string; duration_ms?: number | null }[]
}

export type AgentFinalEvent = {
  type: 'final'
  answer: string
  mode: string
  model_version?: string | null
  sources?: AssistantSource[]
  suggestions?: AgentSuggestion[]
  message_id?: string
  fallback?: boolean
  reason?: string
  process?: AgentProcessTrace | null
  /** 首条问题触发后由后端回写的会话标题；前端据此刷新历史列表 */
  conversation_title?: string
}

export type AgentErrorEvent = { type: 'error'; message: string }

export type AgentEvent =
  | AgentStepEvent
  | AgentDeltaEvent
  | AgentThinkingEvent
  | AgentNoticeEvent
  | AgentFinalEvent
  | AgentErrorEvent

export type AgentReadingContext = {
  note_id?: string
  note_title?: string
  section_title?: string
  excerpt?: string
}

export type AgentNotebookContext = {
  course_id: string | null
  notebook_id: string
  revision: number
  title?: string
  selection?: string
  excerpt?: string
}

export type AgentQuestionPayload = {
  question: string
  scope: AgentScope
  teacher_persona?: string
  material_id?: string
  allow_web?: boolean
  allow_quiz?: boolean
  learning_mode?: 'direct' | 'guided'
  idempotency_key?: string
  reading_context?: AgentReadingContext
  notebook_context?: AgentNotebookContext
}

export type AgentStreamHandlers = {
  onStep?: (event: AgentStepEvent) => void
  onDelta?: (event: AgentDeltaEvent) => void
  onThinking?: (event: AgentThinkingEvent) => void
  onNotice?: (event: AgentNoticeEvent) => void
  onFinal?: (event: AgentFinalEvent) => void
  onError?: (event: AgentErrorEvent) => void
}

/** 解析一段 SSE 缓冲为事件列表，返回未成帧的余量。 */
const FRAME_BOUNDARY = /\r?\n\r?\n/

export function parseAgentStream(buffer: string): { events: AgentEvent[]; rest: string } {
  const events: AgentEvent[] = []
  let rest = buffer
  let boundary = FRAME_BOUNDARY.exec(rest)
  while (boundary) {
    const frame = rest.slice(0, boundary.index).trim()
    rest = rest.slice(boundary.index + boundary[0].length)
    boundary = FRAME_BOUNDARY.exec(rest)
    if (!frame.startsWith('data:')) continue
    try {
      events.push(JSON.parse(frame.slice(5).trim()) as AgentEvent)
    } catch {
      // 单帧损坏只丢这一帧，不断流
    }
  }
  return { events, rest }
}

/** 把剩余缓冲当一帧解析（服务端保证以 \n\n 结尾，这里只作兜底）。 */
export function parseAgentRemainder(buffer: string): AgentEvent[] {
  const frame = buffer.trim()
  if (!frame.startsWith('data:')) return []
  try {
    return [JSON.parse(frame.slice(5).trim()) as AgentEvent]
  } catch {
    return []
  }
}
