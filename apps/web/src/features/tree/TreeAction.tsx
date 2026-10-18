import type { ReactNode, KeyboardEvent } from 'react'

export function TreeAction({ label, onActivate, children, className = '', transform, onFocus, disabled = false }: {
  label: string; onActivate: () => void; children: ReactNode
  className?: string; transform?: string; onFocus?: () => void
  disabled?: boolean
}) {
  const key = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      event.stopPropagation()
      onActivate()
    }
  }
  return <g role={disabled ? undefined : 'button'} tabIndex={disabled ? undefined : 0} aria-label={disabled ? undefined : label} aria-hidden={disabled || undefined} data-forest-interactive={disabled ? undefined : 'true'} pointerEvents={disabled ? 'none' : undefined} className={`kt-action ${className}`} transform={transform} onFocus={disabled ? undefined : onFocus} onKeyDown={disabled ? undefined : key} onClick={disabled ? undefined : event => { event.stopPropagation(); event.currentTarget.focus(); onActivate() }}>
    {children}
  </g>
}
