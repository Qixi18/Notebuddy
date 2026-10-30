import { ApiError, readApiError } from './http'
import { parseAgentRemainder, parseAgentStream } from './agentStream'
import type {
  AgentEvent,
  AgentQuestionPayload,
  AgentStreamHandlers,
} from './agentStream'

export type {
  AgentDeltaEvent,
  AgentErrorEvent,
  AgentEvent,
  AgentFinalEvent,
  AgentNoticeEvent,
  AgentNotebookContext,
  AgentQuestionPayload,
  AgentReadingContext,
  AgentScope,
  AgentStepEvent,
  AgentSuggestion,
  AgentThinkingEvent,
  AgentStreamHandlers,
} from './agentStream'

/**
 * 悬浮坞 agent 的流式客户端：POST SSE（EventSource 不支持 POST，故手写解析）。
 *
 * 事件与后端 ``app/api/v1/agent.py`` 一一对应：
 * step（工具时间线）/ delta（回答增量）/ notice（降级提示）/ final（收尾）/ error。
 * 帧解析规则在 ``./agentStream``（纯函数，可被 node:test 直接测试）。
 */

function dispatchEvent(event: AgentEvent, handlers: AgentStreamHandlers): void {
  if (event.type === 'step') handlers.onStep?.(event)
  else if (event.type === 'delta') handlers.onDelta?.(event)
  else if (event.type === 'thinking') handlers.onThinking?.(event)
  else if (event.type === 'notice') handlers.onNotice?.(event)
  else if (event.type === 'final') handlers.onFinal?.(event)
  else if (event.type === 'error') handlers.onError?.(event)
}

export async function streamAgentMessage(
  conversationId: string,
  payload: AgentQuestionPayload,
  handlers: AgentStreamHandlers,
  signal?: AbortSignal,
): Promise<Extract<AgentEvent, { type: 'final' }>> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/agent-messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    throw await readApiError(response)
  }
  if (!response.body) throw new ApiError('响应缺少流内容', response.status)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalEvent: Extract<AgentEvent, { type: 'final' }> | undefined
  let errorMessage: string | undefined
  const handle = (event: AgentEvent) => {
    dispatchEvent(event, handlers)
    if (event.type === 'final') finalEvent = event
    if (event.type === 'error') errorMessage = event.message
  }
  const IDLE_TIMEOUT_MS = 30_000
  for (;;) {
    let idleTimer: ReturnType<typeof setTimeout> | undefined
    const idle = new Promise<never>((_, reject) => {
      idleTimer = setTimeout(() => reject(new ApiError('连接长时间没有响应，请重试', response.status)), IDLE_TIMEOUT_MS)
    })
    let chunk: Awaited<ReturnType<typeof reader.read>>
    try {
      chunk = await Promise.race([reader.read(), idle])
    } catch (cause) {
      void reader.cancel().catch(() => {})
      throw cause
    } finally {
      clearTimeout(idleTimer)
    }
    const { done, value } = chunk
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parsed = parseAgentStream(buffer)
    buffer = parsed.rest
    for (const event of parsed.events) handle(event)
  }
  for (const event of parseAgentRemainder(buffer + decoder.decode())) handle(event)
  if (!finalEvent) throw new ApiError(errorMessage ?? '智能问答连接中断，未收到最终回答', response.status)
  return finalEvent
}
