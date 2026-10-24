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
}

export type AgentDeltaEvent = { type: 'delta'; text: string }

export type AgentNoticeEvent = { type: 'notice'; text: string }

export type AgentSuggestion =
  | { type: 'note_suggestion'; id: string; note_id: string; note_title: string; impact: string }
  | { type: 'knowledge_proposal'; id: string; name: string }

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
  /** 首条问题触发后由后端回写的会话标题；前端据此刷新历史列表 */
  conversation_title?: string
}

export type AgentErrorEvent = { type: 'error'; message: string }

export type AgentEvent =
  | AgentStepEvent
  | AgentDeltaEvent
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
  course_id: string
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
  idempotency_key?: string
  reading_context?: AgentReadingContext
  notebook_context?: AgentNotebookContext
}

export type AgentStreamHandlers = {
  onStep?: (event: AgentStepEvent) => void
  onDelta?: (event: AgentDeltaEvent) => void
  onNotice?: (event: AgentNoticeEvent) => void
  onFinal?: (event: AgentFinalEvent) => void
  onError?: (event: AgentErrorEvent) => void
}

/** 解析一段 SSE 缓冲为事件列表，返回未成帧的余量。 */
export function parseAgentStream(buffer: string): { events: AgentEvent[]; rest: string } {
  const events: AgentEvent[] = []
  let rest = buffer
  let boundary = rest.indexOf('\n\n')
  while (boundary >= 0) {
    const frame = rest.slice(0, boundary).trim()
    rest = rest.slice(boundary + 2)
    boundary = rest.indexOf('\n\n')
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
