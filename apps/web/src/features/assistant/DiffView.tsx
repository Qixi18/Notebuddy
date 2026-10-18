import type { ReactNode } from 'react'

import type { DiffRow } from './noteDiff'

/** 红删绿增的逐块 diff 视图：每个变更块头部带勾选框，可独立采纳/跳过。
 * 悬浮坞建议卡与笔记内嵌建议共用这套渲染。 */
export function DiffView({ rows, skipped, onToggle }: {
  rows: DiffRow[]
  skipped: Set<string>
  onToggle: (key: string) => void
}) {
  return (
    <div className="agent-diff">
      {rows.map((row, index): ReactNode => {
        const elements: ReactNode[] = []
        const hunkKey = row.hunk
        const hunkStarts = hunkKey !== undefined && rows[index - 1]?.hunk !== hunkKey
        if (hunkStarts) {
          elements.push(
            <label key={`${hunkKey}-head`} className="agent-diff-hunk-head">
              <input
                type="checkbox"
                checked={!skipped.has(hunkKey)}
                onChange={() => onToggle(hunkKey)}
              />
              变更块 {hunkKey.slice(1)}
            </label>,
          )
        }
        elements.push(
          <div
            key={`${hunkKey ?? 'same'}-${index}`}
            className={`agent-diff-row agent-diff-${row.type}`}
          >{row.text || ' '}</div>,
        )
        return elements
      })}
    </div>
  )
}
