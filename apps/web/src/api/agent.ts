import { ApiError } from './http'
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
  AgentQuestionPayload,
  AgentReadingContext,
  AgentScope,
  AgentStepEvent,
  AgentSuggestion,
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
    const body = await response.text()
    let detail = body
    try {
      detail = (JSON.parse(body) as { detail?: string }).detail ?? body
    } catch {
      // 保持原文可读
    }
    throw new ApiError(detail || `请求失败：${response.status}`, response.status)
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
  for (;;) {
    const { done, value } = await reader.read()
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
