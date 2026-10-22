import { useRef, type ReactNode, type KeyboardEvent } from 'react'

export function TreeAction({ label, onActivate, children, className = '', transform, onFocus, disabled = false, describedBy }: {
  label: string; onActivate: () => void; children: ReactNode
  className?: string; transform?: string; onFocus?: () => void
  disabled?: boolean
  describedBy?: string
}) {
  const pointerFocus = useRef(false)
  const key = (event: KeyboardEvent<SVGGElement>) => {
    pointerFocus.current = false
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      event.stopPropagation()
      onActivate()
    }
  }
  return <g role={disabled ? undefined : 'button'} tabIndex={disabled ? undefined : 0} aria-label={disabled ? undefined : label} aria-describedby={disabled ? undefined : describedBy} aria-hidden={disabled || undefined} data-forest-interactive={disabled ? undefined : 'true'} pointerEvents={disabled ? 'none' : undefined} className={`kt-action ${className}`} transform={transform}
    onPointerDown={disabled ? undefined : () => { pointerFocus.current = true }}
    onPointerCancel={() => { pointerFocus.current = false }} onBlur={() => { pointerFocus.current = false }}
    onFocus={disabled ? undefined : () => { if (!pointerFocus.current) onFocus?.() }} onKeyDown={disabled ? undefined : key}
    onClick={disabled ? undefined : event => {
      event.stopPropagation()
      // Mouse/touch focus must not move the target between press and click.
      // Keyboard focus continues to reveal off-screen notes via onFocus.
      pointerFocus.current = true
      event.currentTarget.focus()
      pointerFocus.current = false
      onActivate()
    }}>
    {children}
  </g>
}
