import type { DiffRow } from './noteDiff'

export type NoteChangeItem = {
  /** 建议 id（同一篇笔记可能有多条建议，不能拿 noteId 当 key） */
  id: string
  noteId: string
  noteTitle: string
  chapter?: string | null
  added: number
  removed: number
  status: 'pending' | 'confirmed' | 'rejected'
  preview?: { removed?: string; added?: string; context?: string }
  /** 完整 diff 行：逐行预览用 */
  diff?: DiffRow[]
  /** 应用这条建议后的整篇正文（整篇预览的「改后」视图） */
  proposed?: string
}

/**
 * 右侧「本次改动」：本次会话改过 / 建议改的笔记。
 * 没有数据时收起为 44px 竖条，不占阅读宽度。
 */
export function ChangesPanel({ open, onToggle, items = [], onApplyAll, applying, onPreview }: {
  open: boolean
  onToggle: () => void
  items?: NoteChangeItem[]
  /** 把待确认的建议全部写入笔记 */
  onApplyAll?: () => void
  applying?: boolean
  /** 点条目 → 预览整篇笔记 */
  onPreview?: (item: NoteChangeItem) => void
}) {
  const pending = items.filter((item) => item.status === 'pending')

  if (!open) {
    return (
      <aside className="workspace-changes is-collapsed" aria-label="本次改动">
        <button
          type="button"
          className="workspace-changes-rail"
          onClick={onToggle}
          aria-expanded={false}
          title="展开改动栏"
        >
          <span className="workspace-changes-rail-icon" aria-hidden="true">‹</span>
          <span className="workspace-changes-rail-label">改动 {items.length}</span>
        </button>
      </aside>
    )
  }

  return (
    <aside className="workspace-changes" aria-label="本次改动">
      <header className="workspace-changes-head">
        <strong>本次改动</strong>
        <span className="workspace-changes-count">{items.length}</span>
        <button
          type="button"
          className="workspace-changes-toggle"
          onClick={onToggle}
          aria-expanded
          title="收起改动栏"
        >›</button>
      </header>

      {items.length === 0 ? (
        <div className="workspace-changes-empty">
          <p>这次会话还没有改动笔记。</p>
          <span>在笔记里让我修改时，改动会出现在这里。</span>
        </div>
      ) : (
        <div className="workspace-changes-list">
          {items.map((item) => {
            return (
              <div className="workspace-change-item" key={item.id}>
                <button
                  type="button"
                  className="workspace-change-row"
                  title="预览整篇笔记"
                  onClick={() => onPreview?.(item)}
                >
                  <span className="workspace-change-file" aria-hidden="true">◧</span>
                  <span className="workspace-change-main">
                    <b>{item.noteTitle}</b>
                    <small>{item.chapter ?? '未标注章节'}</small>
                  </span>
                  <span className="workspace-change-diff" aria-label={`新增 ${item.added} 行，删除 ${item.removed} 行`}>
                    <i>+{item.added}</i>{item.removed > 0 && <em>−{item.removed}</em>}
                  </span>
                </button>
              </div>
            )
          })}
        </div>
      )}

      <footer className="workspace-changes-foot">
        <button
          type="button"
          className="workspace-changes-apply"
          disabled={pending.length === 0 || applying || !onApplyAll}
          onClick={onApplyAll}
        >{applying ? '写入中…' : '全部写入笔记'}</button>
      </footer>
    </aside>
  )
}
