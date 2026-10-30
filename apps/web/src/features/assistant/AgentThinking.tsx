import { useState } from 'react'

/**
 * 思维链展示：执行中实时滚动最新思考（限高、只留尾部），结束后折叠成「已深度思考」。
 * 纯展示：内容是模型思维链增量，不进入回答正文与证据；随 final 的 process 落库，
 * 历史消息里由「过程记录」展开回看。
 */

/** 实时态只渲染尾部这么多字：思维链可能很长，全量渲染会让容器一直抖动 */
const LIVE_TAIL_CHARS = 600

function liveTail(thinking: string): string {
  const trimmed = thinking.trimStart()
  if (trimmed.length <= LIVE_TAIL_CHARS) return trimmed
  return `…${trimmed.slice(-LIVE_TAIL_CHARS)}`
}

export function AgentThinking({ thinking, live }: { thinking: string; live: boolean }) {
  const [open, setOpen] = useState(false)
  if (!thinking || !thinking.trim()) return null
  if (live) {
    return (
      <div className="agent-thinking agent-thinking-live" aria-live="polite" aria-label="模型思考中">
        <span className="agent-thinking-head">
          <span className="agent-spinner" aria-hidden="true" />
          <strong>思考中</strong>
        </span>
        <pre className="agent-thinking-body">{liveTail(thinking)}</pre>
      </div>
    )
  }
  return (
    <div className="agent-thinking agent-thinking-done">
      <button
        type="button"
        className="agent-thinking-toggle cursor-interaction"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="agent-thinking-check" aria-hidden="true">✓</span>
        已深度思考{open ? '（点击收起）' : '（点击展开）'}
      </button>
      {open ? <pre className="agent-thinking-body agent-thinking-body-open">{thinking}</pre> : null}
    </div>
  )
}
