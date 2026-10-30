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
 * 右侧「待确认改动（本课程）」：agent 建议改的笔记按篇分组（P4 多目标）。
 * 没有数据时收起为 44px 竖条，不占阅读宽度。
 */
export function ChangesPanel({ open, onToggle, items = [], onApplyAll, applying, onPreview, materials = [] }: {
  open: boolean
  onToggle: () => void
  items?: NoteChangeItem[]
  /** 把待确认的建议全部写入笔记（按笔记分组写入） */
  onApplyAll?: () => void
  applying?: boolean
  /** 点条目 → 预览整篇笔记 */
  onPreview?: (item: NoteChangeItem) => void
  /** 本讲的课件：只读清单，交代这些改动和被引用的资料出自哪几份课件 */
  materials?: Array<{ id: string; lecture_title: string; page_count?: number }>
}) {
  const pending = items.filter((item) => item.status === 'pending')

  if (!open) {
    return (
      <aside className="workspace-changes is-collapsed" aria-label="待确认改动">
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
    <aside className="workspace-changes" aria-label="待确认改动">
      <header className="workspace-changes-head">
        <strong>待确认改动（本课程）</strong>
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
          <p>本课程还没有待确认的笔记改动。</p>
          <span>在对话里让我修改某篇笔记时，改动会出现在这里。</span>
        </div>
      ) : (
        <div className="workspace-changes-list">
          {items.map((item, index) => {
            /* 多目标：按笔记分组展示，换篇时插一行组标题 */
            const newGroup = index === 0 || items[index - 1].noteId !== item.noteId
            return (
              <div key={item.id}>
                {newGroup && (
                  <p className="workspace-change-group" aria-hidden="true">《{item.noteTitle}》</p>
                )}
                <div className="workspace-change-item">
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
              </div>
            )
          })}
        </div>
      )}

      {materials.length > 0 && (
        <section className="workspace-refs" aria-label="本讲资料">
          <p className="workspace-refs-label">本讲资料 <b>{materials.length}</b></p>
          {materials.map((material) => (
            <div className="workspace-refs-row" key={material.id}>
              <span className="workspace-refs-icon" aria-hidden="true">◧</span>
              <span className="workspace-refs-title" title={material.lecture_title}>{material.lecture_title}</span>
              {typeof material.page_count === 'number' && <em>{material.page_count} 页</em>}
            </div>
          ))}
        </section>
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
