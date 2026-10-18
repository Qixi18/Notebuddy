import { useEffect, useRef, useState } from 'react'

export type ContextMenuState = {
  x: number
  y: number
  courseId: string
  courseName: string
} | null

type CourseContextMenuProps = {
  state: ContextMenuState
  onClose: () => void
  onRename: (courseId: string, currentName: string) => void
  onDelete: (courseId: string, courseName: string) => void
}

/** 课程右键菜单：受控定位，点击外部或 Esc 关闭。 */
export function CourseContextMenu({
  state,
  onClose,
  onRename,
  onDelete,
}: CourseContextMenuProps) {
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
    // 滚动时菜单会脱离锚点，直接关闭更符合直觉
    window.addEventListener('scroll', onClose, true)
    return () => {
      window.removeEventListener('mousedown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('scroll', onClose, true)
    }
  }, [state, onClose])

  if (!state) return null

  // 防止菜单溢出视口
  const menuWidth = 168
  const menuHeight = 92
  const left = Math.min(state.x, window.innerWidth - menuWidth - 8)
  const top = Math.min(state.y, window.innerHeight - menuHeight - 8)

  return (
    <div
      className="context-menu"
      ref={menuRef}
      style={{ left, top }}
      role="menu"
      aria-label={`${state.courseName} 操作菜单`}
    >
      <div className="context-menu-title" title={state.courseName}>{state.courseName}</div>
      <button role="menuitem" onClick={() => onRename(state.courseId, state.courseName)}>
        重命名
      </button>
      <button
        role="menuitem"
        className="context-menu-danger"
        onClick={() => onDelete(state.courseId, state.courseName)}
      >
        删除课程
      </button>
    </div>
  )
}

type RenameDialogProps = {
  open: boolean
  initialName: string
  saving: boolean
  onSubmit: (name: string) => void
  onCancel: () => void
}

export function RenameCourseDialog({
  open,
  initialName,
  saving,
  onSubmit,
  onCancel,
}: RenameDialogProps) {
  const [value, setValue] = useState(initialName)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setValue(initialName)
      window.setTimeout(() => inputRef.current?.select(), 0)
    }
  }, [open, initialName])

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
      <div
        className="modal-card"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="重命名课程"
      >
        <h3>重命名课程</h3>
        <p className="modal-hint">课程下的资料、知识点和笔记都会保留。</p>
        <input
          ref={inputRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && trimmed) onSubmit(trimmed)
          }}
          maxLength={200}
          aria-label="课程名称"
        />
        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel}>取消</button>
          <button
            className="primary-button"
            disabled={saving || !trimmed || trimmed === initialName}
            onClick={() => onSubmit(trimmed)}
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

type DeleteDialogProps = {
  open: boolean
  courseName: string
  saving: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteCourseDialog({
  open,
  courseName,
  saving,
  onConfirm,
  onCancel,
}: DeleteDialogProps) {
  const [confirmText, setConfirmText] = useState('')

  useEffect(() => {
    if (open) setConfirmText('')
  }, [open, courseName])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onCancel])

  if (!open) return null

  // 要求输入完整课程名，避免误删整个学期的积累
  const matched = confirmText.trim() === courseName.trim()

  return (
    <div className="modal-backdrop" onClick={onCancel} role="presentation">
      <div
        className="modal-card"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="删除课程"
      >
        <h3 className="modal-danger-title">删除课程</h3>
        <p className="modal-hint">
          课程会移入回收站，资料、知识点与笔记都会保留，可随时恢复。
        </p>
        <p className="modal-hint">
          请输入课程名称 <code>{courseName}</code> 以确认：
        </p>
        <input
          value={confirmText}
          onChange={(event) => setConfirmText(event.target.value)}
          placeholder={courseName}
          aria-label="确认课程名称"
          autoFocus
        />
        <div className="modal-actions">
          <button className="ghost-button" onClick={onCancel}>取消</button>
          <button
            className="danger-button"
            disabled={saving || !matched}
            onClick={onConfirm}
          >
            {saving ? '删除中…' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}
