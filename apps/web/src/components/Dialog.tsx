import { useEffect, useId, useRef, type ReactNode } from 'react'

/** Shared paper dialog: contains focus, protects pending requests and restores its opener. */
export function Dialog({ title, label = title, description, children, onClose, busy = false, closeLabel = '关闭', className = '' }: {
  title: string; label?: string; description?: string; children: ReactNode
  onClose: () => void; busy?: boolean; closeLabel?: string; className?: string
}) {
  const ref = useRef<HTMLElement>(null)
  const opener = useRef(document.activeElement as HTMLElement | null)
  const state = useRef({ busy, onClose })
  state.current = { busy, onClose }
  const descriptionId = useId()

  useEffect(() => {
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const dialog = ref.current
    if (dialog && !dialog.contains(document.activeElement)) {
      (dialog.querySelector<HTMLElement>('input:not(:disabled), select:not(:disabled)') ?? dialog.querySelector<HTMLElement>('button:not(:disabled)') ?? dialog).focus()
    }
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

  return <div className="modal-backdrop" role="presentation" onMouseDown={event => {
    if (event.target === event.currentTarget && !busy) onClose()
  }}>
    <section ref={ref} className={`course-gate-modal botanical-dialog ${className}`} role="dialog" aria-modal="true" aria-label={label} aria-describedby={description ? descriptionId : undefined} aria-busy={busy} tabIndex={-1}>
      <header className="botanical-dialog-header">
        <h2>{title}</h2>
        <button type="button" className="modal-close" aria-label={closeLabel} onClick={onClose} disabled={busy}>
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </button>
      </header>
      {description && <p id={descriptionId} className="botanical-dialog-description">{description}</p>}
      {children}
    </section>
  </div>
}
