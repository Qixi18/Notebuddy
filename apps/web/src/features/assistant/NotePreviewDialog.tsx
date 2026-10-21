import { useEffect, useMemo, useState } from 'react'

import { diffRows } from './noteDiff'

/**
 * 整篇笔记预览：改动栏里点一条建议 → 弹出这篇笔记的完整正文。
 * 两个视图：
 * - 「改动标记」：整篇逐行渲染，变更行带 + 绿 / − 红（与建议卡里的 diff 同一套样式）
 * - 「原文」：改动前的纯正文，用来对照
 */
export function NotePreviewDialog({ open, title, chapter, current, proposed, onClose }: {
  open: boolean
  title: string
  chapter?: string | null
  /** 改动前的正文 */
  current: string
  /** 应用这条建议后的正文 */
  proposed: string
  onClose: () => void
}) {
  const [view, setView] = useState<'marked' | 'before'>('marked')

  useEffect(() => {
    if (!open) return
    setView('marked')
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  const rows = useMemo(() => diffRows(current, proposed), [current, proposed])
  const changeCount = useMemo(
    () => rows.filter((row) => row.type !== 'same').length,
    [rows],
  )

  if (!open) return null

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card note-preview"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`预览笔记 ${title}`}
      >
        <header className="note-preview-head">
          <div>
            <h3>{title}</h3>
            <p className="note-preview-sub">
              {chapter ?? '未标注章节'} · 共 {changeCount} 处改动
            </p>
          </div>
          <div className="note-preview-tabs" role="tablist" aria-label="预览视图">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'marked'}
              className={view === 'marked' ? 'is-active' : undefined}
              onClick={() => setView('marked')}
            >改动标记</button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'before'}
              className={view === 'before' ? 'is-active' : undefined}
              onClick={() => setView('before')}
            >原文</button>
          </div>
        </header>

        <div className="note-preview-body">
          {view === 'before'
            ? <pre className="note-preview-plain">{current || '（这篇笔记还没有正文）'}</pre>
            : (
              <div className="agent-diff note-preview-diff">
                {rows.map((row, index) => (
                  <div key={`${row.hunk ?? 'same'}-${index}`} className={`agent-diff-row agent-diff-${row.type}`}>
                    {row.text || ' '}
                  </div>
                ))}
              </div>
            )}
        </div>

        <div className="modal-actions">
          <span className="note-preview-hint">要采纳或忽略，请回到对话里的建议卡片</span>
          <button className="ghost-button" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  )
}
