/**
 * 实时思考指示器：只表达「模型正在思考」这一状态。
 *
 * 思维链原文属于模型内部推理，既不出现在回答正文/证据里，也不从后端外发、不落库，
 * 所以这里没有可渲染的文本。工具执行摘要、状态与耗时由 AgentSteps 负责展示；
 * 历史消息里的思考总耗时由「过程记录」摘要给出。
 */
export function AgentThinking({ live }: { live: boolean }) {
  if (!live) return null
  return (
    <div className="agent-thinking agent-thinking-live" aria-live="polite" aria-label="模型思考中">
      <span className="agent-thinking-head">
        <span className="agent-spinner" aria-hidden="true" />
        <strong>思考中</strong>
      </span>
    </div>
  )
}
