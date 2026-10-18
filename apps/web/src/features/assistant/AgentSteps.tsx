import type { AgentStepEvent } from '../../api/agent'

/**
 * agent 执行时间线：把流式 step 事件折叠成「执行中 → 完成」两态行。
 * 折叠规则：同一工具的 running 行在收到 done 后被结果行替换，避免时间线无限增长。
 */

const TOOL_LABELS: Record<string, string> = {
  search_course: '检索课程课件',
  read_note: '阅读笔记',
  list_course_notes: '浏览笔记列表',
  search_forest: '跨课程搜索',
  get_note_coverage: '检查课件覆盖',
  explain_term: '定位术语原文',
  web_search: '联网搜索',
  propose_note_edit: '准备笔记修改建议',
  propose_knowledge_node: '提议知识节点',
}

function foldSteps(steps: AgentStepEvent[]): AgentStepEvent[] {
  const visible: AgentStepEvent[] = []
  for (const step of steps) {
    if (step.status === 'done') {
      let runningIndex = -1
      for (let index = visible.length - 1; index >= 0; index -= 1) {
        if (visible[index].status === 'running' && visible[index].tool === step.tool) {
          runningIndex = index
          break
        }
      }
      if (runningIndex >= 0) {
        visible[runningIndex] = step
        continue
      }
    }
    visible.push(step)
  }
  return visible
}

export function AgentSteps({ steps }: { steps: AgentStepEvent[] }) {
  const visible = foldSteps(steps)
  if (visible.length === 0) {
    return <p className="agent-steps agent-steps-empty">正在思考…</p>
  }
  return (
    <ol className="agent-steps" aria-label="agent 执行过程">
      {visible.map((step, index) => (
        <li key={`${step.tool}-${index}`} className={`agent-step agent-step-${step.status}`}>
          <span className="agent-step-icon" aria-hidden="true">{step.status === 'done' ? '✓' : '…'}</span>
          <span className="agent-step-text">{TOOL_LABELS[step.tool] ?? step.tool}{step.detail ? ` · ${step.detail}` : ''}</span>
        </li>
      ))}
    </ol>
  )
}
