import { useEffect, useRef, useState } from 'react'

export type ConversationMenuState = {
  x: number
  y: number
  id: string
  title: string
} | null

/** 会话右键菜单：受控定位，点击外部 / Esc / 滚动关闭。仿 CourseContextMenu。 */
export function ConversationContextMenu({ state, onClose, onRename, onDelete }: {
  state: ConversationMenuState
  onClose: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string, title: string) => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!state) return
    function handlePointerDown(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) onClose()
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('mousedown', handlePointerDown)
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('scroll', onClose, true)
    return () => {
      window.removeEventListener('mousedown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [state, onClose])

  if (!state) return null

  const menuWidth = 152
  const menuHeight = 84
  const left = Math.min(state.x, window.innerWidth - menuWidth - 8)
  const top = Math.min(state.y, window.innerHeight - menuHeight - 8)

  return (
    <div className="context-menu" ref={menuRef} style={{ left, top }} role="menu" aria-label={`${state.title} 操作菜单`}>
      <div className="context-menu-title" title={state.title}>{state.title || '未命名会话'}</div>
      <button role="menuitem" onClick={() => onRename(state.id, state.title)}>重命名</button>
      <button
        role="menuitem"
        className="context-menu-danger"
        onClick={() => onDelete(state.id, state.title)}
      >
        删除会话
      </button>
    </div>
  )
}

export function RenameConversationDialog({ open, initialTitle, saving, error, onSubmit, onCancel }: {
  open: boolean
  initialTitle: string
  saving: boolean
  /** 上一次提交失败的原因；非空时对话框保持打开并显示，避免「点了没反应」 */
  error?: string
  onSubmit: (title: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(initialTitle)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setValue(initialTitle)
      window.setTimeout(() => inputRef.current?.select(), 0)
    }
  }, [open, initialTitle])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onCancel])

  if (!open) return null
  const trimmed = value.trim()

  return (
    <div className="modal-backdrop" onClick={onCancel} role="presentation">
      <div className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="重命名会话">
        <h3>重命名会话</h3>
        <p className="modal-hint">改个更好认的名字，方便以后在历史里找回。</p>
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && trimmed && trimmed !== initialTitle) onSubmit(trimmed) }}
          maxLength={300}
          aria-label="会话标题"
        />
        {error && <p className="modal-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel}>取消</button>
          <button
            className="primary-button"
            disabled={saving || !trimmed || trimmed === initialTitle}
            onClick={() => onSubmit(trimmed)}
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function DeleteConversationDialog({ open, title, saving, error, onConfirm, onCancel }: {
  open: boolean
  title: string
  saving: boolean
  /** 上一次删除失败的原因；非空时对话框保持打开并显示，避免「点了没反应」 */
  error?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="modal-backdrop" onClick={onCancel} role="presentation">
      <div className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="删除会话">
        <h3 className="modal-danger-title">删除会话</h3>
        <p className="modal-hint">
          将永久删除会话 <b>{title || '未命名会话'}</b> 及其全部问答内容，不可恢复。
        </p>
        <p className="modal-hint">课程资料与笔记不受影响。</p>
        {error && <p className="modal-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel}>取消</button>
          <button className="danger-button" disabled={saving} onClick={onConfirm}>
            {saving ? '删除中…' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}
