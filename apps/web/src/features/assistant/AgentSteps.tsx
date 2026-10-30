import type { AgentRunStep } from '../conversation/useConversation'

/**
 * agent 执行时间线：每个工具一行，执行中转圈、完成显示耗时。
 * 步骤的 running→done 折叠与计时已在 useConversation 累积时完成，这里只做纯渲染。
 */

const TOOL_META: Record<string, { label: string; icon: string }> = {
  search_course: { label: '检索课程资料', icon: 'search' },
  read_note: { label: '阅读小节', icon: 'file-text' },
  list_course_notes: { label: '浏览小节列表', icon: 'list' },
  list_course_materials: { label: '列出课程资料', icon: 'folder-open' },
  read_material_page: { label: '阅读资料页', icon: 'file-text' },
  search_forest: { label: '跨课程搜索', icon: 'search' },
  get_note_coverage: { label: '检查收录覆盖', icon: 'clipboard-check' },
  explain_term: { label: '定位术语原文', icon: 'quote' },
  web_search: { label: '联网搜索', icon: 'globe' },
  generate_quiz: { label: '生成测验题目', icon: 'clipboard-list' },
  generate_review_outline: { label: '整理复习提纲', icon: 'list-checks' },
  generate_concept_contrast: { label: '辨析易混概念', icon: 'git-compare' },
  propose_note_edits: { label: '准备小节修改建议', icon: 'pen-line' },
  create_note_suggestion: { label: '起草新增小节建议', icon: 'file-plus' },
  propose_knowledge_node: { label: '提议知识节点', icon: 'network' },
}

function formatDuration(ms?: number): string {
  if (!ms || ms < 100) return ''
  if (ms < 1000) return '<1s'
  return `${(ms / 1000).toFixed(1)}s`
}

function foldSteps(steps: AgentRunStep[]): AgentRunStep[] {
  /* 同工具的 done 替换掉还在转圈的 running 行（useConversation 已做一层，
      这里兜底：直接构造的 steps 数组（测试/重放）也保持一工具一行）。 */
  const visible: AgentRunStep[] = []
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

export function AgentSteps({ steps }: { steps: AgentRunStep[] }) {
  const visible = foldSteps(steps)
  if (visible.length === 0) return null
  return (
    <ol className="agent-steps" aria-label="agent 执行过程">
      {visible.map((step, index) => {
        const meta = TOOL_META[step.tool]
        const running = step.status === 'running'
        return (
          <li key={`${step.tool}-${index}`} className={`agent-step agent-step-${step.status}`}>
            <span className={`agent-step-icon${running ? ' agent-step-icon-running' : ''}`} aria-hidden="true">
              {running
                ? <span className="agent-spinner" />
                : <i data-lucide={meta?.icon ?? 'check'} />}
            </span>
            <span className="agent-step-text">
              <strong>{meta?.label ?? step.tool}</strong>
              {step.detail ? <em>{step.detail}</em> : null}
            </span>
            {!running && step.durationMs ? (
              <span className="agent-step-duration tabular-nums">{formatDuration(step.durationMs)}</span>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
