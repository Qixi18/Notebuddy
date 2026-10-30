import { useEffect, useRef } from 'react'

export function useHistoryDialog(onClose: () => void, busy: boolean) {
  const ref = useRef<HTMLDivElement>(null)
  const opener = useRef(document.activeElement as HTMLElement | null)
  const state = useRef({ onClose, busy })
  state.current = { onClose, busy }
  useEffect(() => {
    const dialog = ref.current
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ;(dialog?.querySelector<HTMLButtonElement>('button:not(:disabled)') ?? dialog)?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (Array.from(document.querySelectorAll('[role="dialog"]')).at(-1) !== dialog) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        if (!state.current.busy) state.current.onClose()
      }
      if (event.key !== 'Tab') return
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? [])
      const first = controls[0], last = controls.at(-1)
      if (!first) { event.preventDefault(); dialog?.focus(); return }
      if (!dialog?.contains(document.activeElement) || document.activeElement === dialog || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first)?.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      document.body.style.overflow = overflow
      if (opener.current?.isConnected) opener.current.focus()
    }
  }, [])
  useEffect(() => {
    if (busy && !ref.current?.contains(document.activeElement)) ref.current?.focus()
  }, [busy])
  return ref
}

export function historyOriginLabel(origin: string): string {
  switch (origin) {
    case 'ai_append': return 'AI 生成'
    case 'ai_suggestion': return 'AI 修改'
    case 'restore': return '历史恢复'
    case 'autosave': return '自动保存'
    default: return '保存版本'
  }
}
